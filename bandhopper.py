# -*- coding: utf-8 -*-

import socket
import threading
import time
import sys
import signal
import shutil
import select
import tty
import termios
import os
import json
import math
from datetime import datetime, timezone, date

HOST = "127.0.0.1"
SDR_HOST = "127.0.0.1"

running = True

# -------------------------
# SETTINGS FILE
# -------------------------

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bandhopper_settings.json")

DEFAULT_SETTINGS = {
    "callsign":      "",
    "locator":       "",
    "hopping_mode":  "DAY/NIGHT",
    "band_cycles":   {
        "160m": 10, "80m": 10, "40m": 10, "30m": 10, "20m": 10,
        "17m": 10, "15m": 10, "12m": 10, "10m": 10,
        "6m/EU": 10, "6m/NA": 10, "4m": 10, "2m": 10
    },
    "selected_bands": ["160m","80m","40m","30m","20m","17m","15m","12m","10m"],
    "grayline_window": 30,
    "proxy_port": 4533,
    "sdr_port":   4532,
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
            # merge with defaults to handle missing keys
            merged = dict(DEFAULT_SETTINGS)
            merged.update(data)
            return merged
        except:
            pass
    return dict(DEFAULT_SETTINGS)

def save_settings():
    data = {
        "callsign":       callsign,
        "locator":        locator,
        "hopping_mode":   current_mode,
        "band_cycles":    band_cycles,
        "selected_bands": sorted(selected_bands),
        "grayline_window": GRAYLINE_WINDOW,
        "proxy_port":     proxy_port,
        "sdr_port":       sdr_port_setting,
    }
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except:
        pass

# -------------------------
# STATE
# -------------------------

band_index = 0
current_freq = None
current_label = None

wsjtx_last_seen = 0
sdr_ok = False

cycle_counter = 0
last_slot = -1

CYCLE_SECONDS = 15

# -------------------------
# HOPPING MODES
# -------------------------

MODE_DAYNIGHT  = "DAY/NIGHT"
MODE_GRAYLINE  = "DAY/NIGHT+GL"
MODE_ALLBANDS  = "OFF"

# -------------------------
# LOAD SETTINGS
# -------------------------

_s = load_settings()

proxy_port       = _s.get("proxy_port", 4533)
sdr_port_setting = _s.get("sdr_port", 4532)
callsign         = _s.get("callsign", "")
locator         = _s["locator"]
current_mode    = _s["hopping_mode"]
band_cycles     = _s.get("band_cycles", dict(DEFAULT_SETTINGS["band_cycles"]))
selected_bands  = set(_s["selected_bands"])
GRAYLINE_WINDOW = _s.get("grayline_window", 30)

# -------------------------
# UI STATE
# -------------------------

UI_DASHBOARD  = "dashboard"
UI_MENU       = "menu"
UI_MODE_SEL   = "mode_sel"
UI_CYCLES     = "cycles"
UI_BANDS      = "bands"
UI_SETTINGS   = "settings"
UI_WELCOME    = "welcome"
UI_BANDRULES  = "bandrules"

# first run = settings file didn't exist before loading
_first_run = not os.path.exists(SETTINGS_FILE)

ui_screen        = UI_WELCOME if _first_run else UI_DASHBOARD
menu_cursor      = 0
mode_cursor      = 0
cycles_cursor    = 9
bands_cursor     = 0
settings_cursor  = 0
settings_active  = None   # None | "callsign" | "locator" | "proxy_port" | "sdr_port"
restart_required = False
port_input       = ""
bandrules_cursor  = 0
bandrules_col     = 0  # 0=band col, 1=cycles col
bandrules_editing = False
bandrules_input   = ""
pending_rules     = None  # {label: cycles}
pending_rules_sel = None  # set of selected bands
settings_return  = UI_MENU  # where to go on ESC/BACK from settings
settings_return_mode = None  # mode that was attempted before redirect to settings
pending_mode     = None
pending_cycles   = None
pending_bands    = None
callsign_input   = ""
locator_input    = ""

# -------------------------
# COLORS
# -------------------------

GREEN_BG  = "\033[42m\033[30m"
RED_BG    = "\033[41m\033[30m"
RESET     = "\033[0m"
REVERSE   = "\033[7m"
DIM       = "\033[2m"
HEADER_BG = "\033[7m"   # reverse video — works on all terminals
FOOTER_BG = "\033[7m"   # same

CLEAR    = "\033[0m\033[2J\033[H"
HIDE_CUR = "\033[?25l"
SHOW_CUR = "\033[?25h"

# -------------------------
# BAND PLAN
# -------------------------

BANDS_DAY = [
    (14074000,  "20m"),
    (18100000,  "17m"),
    (21074000,  "15m"),
    (24915000,  "12m"),
    (28074000,  "10m"),
    (10136000,  "30m"),
]

BANDS_NIGHT = [
    (1840000,   "160m"),
    (3573000,   "80m"),
    (7074000,   "40m"),
    (10136000,  "30m"),
]

# VHF bands — active day and night
BANDS_VHF = [
    (50313000,  "6m/EU"),
    (50323000,  "6m/NA"),
    (70154000,  "4m"),
    (144174000, "2m"),
]

BANDS_ALL = [
    (1840000,   "160m"),
    (3573000,   "80m"),
    (7074000,   "40m"),
    (10136000,  "30m"),
    (14074000,  "20m"),
    (18100000,  "17m"),
    (21074000,  "15m"),
    (24915000,  "12m"),
    (28074000,  "10m"),
    (50313000,  "6m/EU"),
    (50323000,  "6m/NA"),
    (70154000,  "4m"),
    (144174000, "2m"),
]

# Labels for freq display in BAND SELECTION menu
BAND_FREQ_LABEL = {
    "160m":  "1.840 MHz",
    "80m":   "3.573 MHz",
    "40m":   "7.074 MHz",
    "30m":   "10.136 MHz",
    "20m":   "14.074 MHz",
    "17m":   "18.100 MHz",
    "15m":   "21.074 MHz",
    "12m":   "24.915 MHz",
    "10m":   "28.074 MHz",
    "6m/EU": "50.313 MHz",
    "6m/NA": "50.323 MHz",
    "4m":    "70.154 MHz",
    "2m":    "144.174 MHz",
}

DAY_LABELS   = {l for _, l in BANDS_DAY}
NIGHT_LABELS = {l for _, l in BANDS_NIGHT}
VHF_LABELS   = {l for _, l in BANDS_VHF}

def locator_set():
    return bool(locator) and validate_locator(locator)

def auto_available():
    return locator_set() and bool(selected_bands & DAY_LABELS) and bool(selected_bands & NIGHT_LABELS)

def grayline_available():
    return locator_set() and auto_available()

# -------------------------
# LOCATOR / GRAYLINE MATH
# -------------------------

def locator_to_latlon(loc):
    """Convert Maidenhead locator to (lat, lon) in degrees."""
    loc = loc.upper().strip()
    lon = (ord(loc[0]) - ord('A')) * 20 - 180
    lat = (ord(loc[1]) - ord('A')) * 10 - 90
    lon += int(loc[2]) * 2
    lat += int(loc[3]) * 1
    if len(loc) >= 6:
        lon += (ord(loc[4]) - ord('A')) * (2/24)
        lat += (ord(loc[5]) - ord('A')) * (1/24)
        lon += 1/24
        lat += 1/48
    else:
        lon += 1.0
        lat += 0.5
    return lat, lon

def validate_locator(loc):
    """Return True if locator is valid Maidenhead (4 or 6 chars)."""
    loc = loc.upper().strip()
    if len(loc) not in (4, 6):
        return False
    if not ('A' <= loc[0] <= 'R' and 'A' <= loc[1] <= 'R'):
        return False
    if not (loc[2].isdigit() and loc[3].isdigit()):
        return False
    if len(loc) == 6:
        if not ('A' <= loc[4] <= 'X' and 'A' <= loc[5] <= 'X'):
            return False
    return True

def sun_times_utc(lat_deg, lon_deg, d=None):
    """
    Calculate sunrise and sunset UTC times for given lat/lon and date.
    Returns (sunrise_minutes_utc, sunset_minutes_utc).
    Uses NOAA algorithm in pure Python math.
    """
    if d is None:
        d = date.today()

    lat = math.radians(lat_deg)

    # Julian date
    jd = 367 * d.year \
       - int(7 * (d.year + int((d.month + 9) / 12)) / 4) \
       + int(275 * d.month / 9) \
       + d.day + 1721013.5

    # Julian century
    jc = (jd - 2451545.0) / 36525.0

    # Geometric mean longitude of sun (deg)
    gml = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360

    # Geometric mean anomaly (deg)
    gma = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    gma_r = math.radians(gma)

    # Equation of center
    eoc = math.sin(gma_r) * (1.914602 - jc * (0.004817 + 0.000014 * jc)) \
        + math.sin(2 * gma_r) * (0.019993 - 0.000101 * jc) \
        + math.sin(3 * gma_r) * 0.000289

    # Sun's true longitude
    stl = gml + eoc

    # Sun's apparent longitude
    sal = stl - 0.00569 - 0.00478 * math.sin(math.radians(125.04 - 1934.136 * jc))

    # Mean obliquity of ecliptic
    moe = 23 + (26 + ((21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813)))) / 60) / 60
    oc = moe + 0.00256 * math.cos(math.radians(125.04 - 1934.136 * jc))
    oc_r = math.radians(oc)

    # Sun declination
    decl = math.asin(math.sin(oc_r) * math.sin(math.radians(sal)))

    # Equation of time (minutes)
    y = math.tan(oc_r / 2) ** 2
    sal_r = math.radians(stl)
    eot = 4 * math.degrees(
        y * math.sin(2 * sal_r)
        - 2 * 0.016708634 * math.sin(gma_r)
        + 4 * 0.016708634 * y * math.sin(gma_r) * math.cos(2 * sal_r)
        - 0.5 * y * y * math.sin(4 * sal_r)
        - 1.25 * 0.016708634 ** 2 * math.sin(2 * gma_r)
    )

    # Hour angle at sunrise (deg)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(lat) * math.cos(decl))
              - math.tan(lat) * math.tan(decl))
    cos_ha = max(-1.0, min(1.0, cos_ha))  # clamp for polar regions
    ha = math.degrees(math.acos(cos_ha))

    # Solar noon (minutes UTC)
    noon = 720 - 4 * lon_deg - eot

    sunrise = noon - ha * 4   # minutes UTC
    sunset  = noon + ha * 4   # minutes UTC

    return sunrise, sunset

def grayline_status():
    """
    Returns (in_grayline, minutes_to_next_grayline).
    Uses GRAYLINE_WINDOW minutes either side of sunrise/sunset.
    """
    if not locator or not validate_locator(locator):
        return False, None

    try:
        lat, lon = locator_to_latlon(locator)
        sunrise, sunset = sun_times_utc(lat, lon)
    except:
        return False, None

    now = utc()
    now_min = now.hour * 60 + now.minute + now.second / 60.0
    w = GRAYLINE_WINDOW

    events = [sunrise, sunset]
    in_gl = False
    for ev in events:
        if (ev - w) <= now_min <= (ev + w):
            in_gl = True
            break

    if in_gl:
        return True, 0

    # find seconds to next gray line start
    candidates = []
    for ev in events:
        start = ev - w
        diff = (start - now_min) * 60  # convert to seconds
        if diff < 0:
            diff += 86400  # next day in seconds
        candidates.append(diff)

    return False, int(min(candidates))

def is_grayline_active():
    in_gl, _ = grayline_status()
    return in_gl

# -------------------------
# TERMINAL
# -------------------------

def width():
    return shutil.get_terminal_size((80, 20)).columns

def hr(w):
    return "=" * w

def header(title, w):
    sys.stdout.write(f"{HEADER_BG}{title.center(w)}{RESET}\r\n")

def footer(text, w):
    sys.stdout.write(f"{FOOTER_BG}{text.center(w)}{RESET}\r\n")
    sys.stdout.write("\r\n" + "buycoffee.to/sq5wbw".center(w) + "\r\n")

def out(text=""):
    sys.stdout.write(text + "\r\n")

def flush():
    sys.stdout.flush()

# -------------------------
# SDR
# -------------------------

class SDR:
    def __init__(self):
        self.sock = None
        self._lock = threading.Lock()
        threading.Thread(target=self._connect_loop, daemon=True).start()

    def _connect_loop(self):
        global sdr_ok
        while running:
            try:
                s = socket.socket()
                s.settimeout(3)
                s.connect((SDR_HOST, sdr_port_setting))
            except Exception:
                sdr_ok = False
                time.sleep(2)
                continue

            with self._lock:
                if self.sock:
                    try: self.sock.close()
                    except: pass
                self.sock = s
            sdr_ok = True

            while running:
                time.sleep(3)
                with self._lock:
                    if self.sock is None:
                        break
                    try:
                        self.sock.sendall(b"f\n")
                        data = self.sock.recv(64)
                        if not data:
                            raise ConnectionError("empty response")
                        sdr_ok = True
                    except Exception:
                        sdr_ok = False
                        try: self.sock.close()
                        except: pass
                        self.sock = None
                        break

    def send(self, cmd):
        global sdr_ok
        with self._lock:
            if self.sock is None:
                return "RPRT -1"
            try:
                self.sock.sendall((cmd + "\n").encode())
                resp = self.sock.recv(1024).decode().strip()
                return resp
            except Exception:
                sdr_ok = False
                try: self.sock.close()
                except: pass
                self.sock = None
                return "RPRT -1"

sdr = SDR()

# -------------------------
# TIME / SLOTS
# -------------------------

def utc():
    return datetime.now(timezone.utc)

def ft8_slot():
    return int(time.time() // 15)

def is_new_slot():
    global last_slot
    s = ft8_slot()
    if s != last_slot:
        last_slot = s
        return True
    return False

# -------------------------
# BAND LOGIC
# -------------------------

def is_daytime():
    """Returns True if current UTC time is between sunrise and sunset."""
    if locator and validate_locator(locator):
        try:
            lat, lon = locator_to_latlon(locator)
            sunrise, sunset = sun_times_utc(lat, lon)
            now = utc()
            now_min = now.hour * 60 + now.minute + now.second / 60.0
            return sunrise <= now_min <= sunset
        except:
            pass
    # fallback: fixed UTC window
    return 6 <= utc().hour < 16

def bands():
    if current_mode == MODE_GRAYLINE and is_grayline_active():
        pool = BANDS_ALL
    elif current_mode == MODE_ALLBANDS:
        pool = BANDS_ALL
    elif current_mode in (MODE_DAYNIGHT, MODE_GRAYLINE):
        hf_pool = BANDS_DAY if is_daytime() else BANDS_NIGHT
        vhf_pool = BANDS_VHF
        pool = hf_pool + vhf_pool
    else:
        pool = BANDS_ALL
    filtered = [(f, l) for f, l in pool if l in selected_bands]
    return filtered if filtered else pool

def get_band(i):
    b = bands()
    return b[i % len(b)]

def fmt(f):
    return f"{f/1_000_000:.3f} MHz"

# -------------------------
# INIT / SWITCH / ENGINE
# -------------------------

def init():
    global current_freq, current_label
    current_freq, current_label = get_band(band_index)
    # Send initial frequency in background — waits for SDR to connect
    def _send_when_ready():
        for _ in range(300):  # wait up to 60s
            if sdr_ok:
                sdr.send(f"F {current_freq}")
                return
            time.sleep(0.2)
    threading.Thread(target=_send_when_ready, daemon=True).start()

def switch():
    global band_index, current_freq, current_label, cycle_counter
    band_index += 1
    current_freq, current_label = get_band(band_index)
    cycle_counter = 0
    sdr.send(f"F {current_freq}")

def current_cycle_limit():
    """Return cycle limit for the current band."""
    return band_cycles.get(current_label, 10)

def engine():
    global cycle_counter
    while running:
        time.sleep(0.1)
        if not is_new_slot():
            continue
        # only count cycles when both WSJT-X and SDR++ are connected
        wsjtx_up = (time.time() - wsjtx_last_seen) < 5
        if not (wsjtx_up and sdr_ok):
            continue
        cycle_counter += 1
        if cycle_counter >= current_cycle_limit():
            switch()

# -------------------------
# TIMER
# -------------------------

def next_switch():
    remaining = current_cycle_limit() - cycle_counter
    sec = CYCLE_SECONDS - (time.time() % CYCLE_SECONDS)
    if remaining <= 0:
        return 0
    return int((remaining - 1) * CYCLE_SECONDS + sec)

# -------------------------
# UI HELPERS
# -------------------------

def bar(n, total=None):
    if total is None:
        total = current_cycle_limit()
    w = total
    f = min(int(n), w)
    return "[" + "#" * f + "-" * (w - f) + "]"

def status():
    ws = GREEN_BG + " WSJT-X " + RESET if (time.time() - wsjtx_last_seen) < 5 else RED_BG + " WSJT-X " + RESET
    sd = GREEN_BG + " SDR++ " + RESET if sdr_ok else RED_BG + " SDR++ " + RESET
    return f"{ws} {sd}"

def active_bands_label():
    """Dynamic label for ACTIVE BANDS based on current mode and time."""
    if current_mode == MODE_ALLBANDS:
        return "ALL BANDS"
    if current_mode == MODE_GRAYLINE and is_grayline_active():
        return "ALL BANDS"
    if current_mode in (MODE_DAYNIGHT, MODE_GRAYLINE):
        return "DAY BANDS" if is_daytime() else "NIGHT BANDS"
    return "ALL BANDS"

def bands_view():
    b = bands()
    result = []
    for f, l in b:
        if l == current_label:
            result.append(GREEN_BG + l + RESET)
        else:
            result.append(l)
    return " ".join(result)

def fmt_secs(secs):
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def fmt_cycle_time(total_secs):
    """Format cycle time: (15s) below 60s, (01:30s) above."""
    if total_secs < 60:
        return f"({total_secs}s)"
    else:
        m = total_secs // 60
        s = total_secs % 60
        return f"({m:02d}:{s:02d}s)"

# -------------------------
# RENDER: DASHBOARD
# -------------------------

def render_dashboard():
    w = width()

    sys.stdout.write(CLEAR)
    sys.stdout.write(HIDE_CUR)

    wsjtx_up = (time.time() - wsjtx_last_seen) < 5
    both_up  = wsjtx_up and sdr_ok
    one_up   = wsjtx_up or sdr_ok

    single = len(bands()) == 1
    nxt_f, nxt_l = get_band(band_index + 1)
    sec = next_switch()

    header("BANDHOPPER 1.0 by SQ5WBW & AI", w)
    out()

    out(f"  STATUS        : {status()}")
    out(f"  AI HOPPING    : {current_mode}")
    out()

    out(f"  TIME UTC      : {utc().strftime('%H:%M:%S')}")

    if current_mode == MODE_GRAYLINE:
        in_gl, secs = grayline_status()
        if in_gl:
            out(f"  GRAYLINE IN   : {GREEN_BG}NOW!{RESET}")
        elif secs is not None:
            out(f"  GRAYLINE IN   : {fmt_secs(secs)}")
        out()

    out(f"  CURRENT BAND  : {fmt(current_freq)} ({current_label})")
    if single:
        out(f"  NEXT BAND     : OUT OF HOPS")
    else:
        out(f"  NEXT BAND     : {fmt(nxt_f)} ({nxt_l})")
    out()

    if not both_up:
        waiting = "Warming up tubes" if not one_up else "QRV soon"
        out(f"  NEXT HOP      : {waiting}")
        out(f"  CYCLE TIMER   : {waiting}")
    elif single:
        out(f"  NEXT HOP      : OUT OF HOPS")
        slot_sec = time.time() % CYCLE_SECONDS
        out(f"  CYCLE TIMER   : {bar(slot_sec, CYCLE_SECONDS)} {int(slot_sec)} / {CYCLE_SECONDS}s")
    else:
        out(f"  NEXT HOP      : {sec//60:02d}:{sec%60:02d}")
        cl = current_cycle_limit()
        if cl == 1:
            slot_sec = time.time() % CYCLE_SECONDS
            out(f"  CYCLE TIMER   : {bar(slot_sec, CYCLE_SECONDS)} {int(slot_sec)} / {CYCLE_SECONDS}s")
        else:
            out(f"  CYCLE TIMER   : {bar(cycle_counter)} {cycle_counter}/{cl}")
    out()

    out(f"  {active_bands_label():<13} : {bands_view()}")
    out()
    footer("Press 'm' = MENU | Ctrl+C = QUIT", w)

    flush()

# -------------------------
# RENDER: MENU
# -------------------------

MENU_ITEMS = ["AI HOPPING", "BANDS", "SETTINGS", "BACK"]

def render_menu():
    w = width()

    sys.stdout.write(CLEAR)
    sys.stdout.write(HIDE_CUR)

    header("BANDHOPPER 1.0 by SQ5WBW & AI", w)
    out()
    out(f"  MENU")
    out()

    for i, item in enumerate(MENU_ITEMS):
        if item == "BACK":
            out()
        if i == menu_cursor:
            out(f"{REVERSE}  ► {item}{RESET}")
        else:
            out(f"    {item}")

    out()
    footer("↑↓ = NAVIGATE | Enter = SELECT | Esc = BACK", w)

    flush()

# -------------------------
# RENDER: HOPPING MODE
# -------------------------

MODE_ITEMS = [MODE_DAYNIGHT, MODE_GRAYLINE, MODE_ALLBANDS, "BACK"]
MODE_LABELS = {
    MODE_DAYNIGHT: "DAY/NIGHT",
    MODE_GRAYLINE: "DAY/NIGHT+GRAYLINE",
    MODE_ALLBANDS: "OFF",
    "BACK":        "BACK",
}

def render_mode_sel():
    w = width()

    sys.stdout.write(CLEAR)
    sys.stdout.write(HIDE_CUR)

    header("BANDHOPPER 1.0 by SQ5WBW & AI", w)
    out()
    out(f"  AI HOPPING")
    out()

    for i, item in enumerate(MODE_ITEMS):
        effective    = pending_mode if pending_mode is not None else current_mode
        active       = (item != "BACK" and item == effective)
        cursor       = (i == mode_cursor)
        label        = MODE_LABELS[item]

        unavail_dn   = (item == MODE_DAYNIGHT  and not auto_available())
        unavail_gl   = (item == MODE_GRAYLINE  and not grayline_available())
        unavail      = unavail_dn or unavail_gl

        if item == "BACK":
            out()
            out(f"{REVERSE}  ► BACK{RESET}" if cursor else f"    BACK")
        elif unavail:
            hint = "(set your GRID in SETTINGS)"
            if cursor:
                out(f"{REVERSE}  ► {label}  {hint}{RESET}")
            else:
                out(f"    {DIM}{label}  {hint}{RESET}")
        elif cursor:
            out(f"{REVERSE}  ► {label}{RESET}")
        elif active:
            out(f"    {GREEN_BG}{label}{RESET}")
        else:
            out(f"    {label}")

    out()
    footer("↑↓ = NAVIGATE | Enter = SELECT | Esc = BACK", w)

    flush()

# -------------------------
# RENDER: FT8 CYCLES
# -------------------------

CYCLES_MIN = 1
CYCLES_MAX = 15

def render_cycles():
    w = width()

    sys.stdout.write(CLEAR)
    sys.stdout.write(HIDE_CUR)

    header("BANDHOPPER 1.0 by SQ5WBW & AI", w)
    out()
    out(f"  BAND HOP FREQUENCY")
    out()

    effective = pending_cycles if pending_cycles is not None else CYCLE_LIMIT

    import re as _re
    def vis(s): return len(_re.sub(r'\033\[[^m]*m', '', s))

    col_w = 20  # fixed column width

    for row in range(10):
        left_n  = row + 1    # 1-10
        right_n = row + 11   # 11-15

        left_idx  = row
        right_idx = row + 10

        # left cell — always 1-10
        label_l = f"[{left_n}] FT8 CYCLE" if left_n == 1 else f"[{left_n}] FT8 CYCLES"
        if left_idx == cycles_cursor:
            cell_l = f"{REVERSE}  ► {label_l}{RESET}"
        elif left_n == effective:
            cell_l = f"    {GREEN_BG}{label_l}{RESET}"
        else:
            cell_l = f"    {label_l}"

        # right cell — 11-15 on rows 0-4, blank rows 5-8, BACK on row 9
        if right_n <= 15:
            label_r = f"[{right_n}] FT8 CYCLES"
            if right_idx == cycles_cursor:
                cell_r = f"{REVERSE}  ► {label_r}{RESET}"
            elif right_n == effective:
                cell_r = f"    {GREEN_BG}{label_r}{RESET}"
            else:
                cell_r = f"    {label_r}"
        elif row == 6:  # blank separator before BACK
            cell_r = ""
        elif row == 7:  # BACK
            if cycles_cursor == CYCLES_MAX:
                cell_r = f"{REVERSE}  ► BACK{RESET}"
            else:
                cell_r = f"    BACK"
        else:
            cell_r = ""

        pad = col_w - vis(cell_l)
        out(cell_l + " " * max(2, pad) + cell_r)

    out()
    footer("←↑↓→ = NAVIGATE | Enter = SELECT | Esc = BACK", w)

    flush()

# -------------------------
# RENDER: BAND SELECTION
# -------------------------

def render_bands():
    w = width()

    sys.stdout.write(CLEAR)
    sys.stdout.write(HIDE_CUR)

    header("BANDHOPPER 1.0 by SQ5WBW & AI", w)
    out()
    out(f"  BAND SELECTION")
    out()

    effective = pending_bands if pending_bands is not None else selected_bands
    items = list(BANDS_ALL) + [("BACK", "BACK")]

    for idx, (freq, label) in enumerate(items):
        cursor = (idx == bands_cursor)
        if label == "BACK":
            out()
            out(f"{REVERSE}  ► BACK{RESET}" if cursor else f"    BACK")
        else:
            checked = label in effective
            box = "[#]" if checked else "[ ]"
            freq_str = BAND_FREQ_LABEL.get(label, "")
            display = f"{label} ({freq_str})"
            if cursor:
                out(f"{REVERSE}  ► {box} {display}{RESET}")
            elif checked:
                out(f"    {GREEN_BG}{box} {display}{RESET}")
            else:
                out(f"    {box} {display}")

    out()
    footer("↑↓ = NAVIGATE | Enter = SELECT | Esc = BACK", w)

    flush()

# -------------------------
# RENDER: SETTINGS
# -------------------------

SETTINGS_ITEMS = ["MY CALLSIGN", "MY GRID", "PROXY_SEP", "WSJT-X PORT", "SDR++ PORT", "BACK"]
# navigable items (exclude separator)
SETTINGS_NAV = [x for x in SETTINGS_ITEMS if x != "PROXY_SEP"]

def validate_port(s):
    try:
        v = int(s)
        return 1024 <= v <= 65535
    except:
        return False

def render_settings():
    w = width()

    sys.stdout.write(CLEAR)
    sys.stdout.write(HIDE_CUR)

    header("BANDHOPPER 1.0 by SQ5WBW & AI", w)
    out()
    out(f"  SETTINGS")
    out()

    nav_idx = 0
    for item in SETTINGS_ITEMS:
        if item == "PROXY_SEP":
            out()
            out(f"  PROXY")
            continue

        cursor = (nav_idx == settings_cursor)
        nav_idx += 1

        if item == "BACK":
            out()
            out(f"{REVERSE}  ► BACK{RESET}" if cursor else f"    BACK")

        elif item == "MY CALLSIGN":
            if settings_active == "callsign":
                inp = callsign_input.upper()
                out(f"{REVERSE}  ► MY CALLSIGN : {GREEN_BG} {inp}_ {RESET}")
            elif cursor:
                val = callsign if callsign else "(not set)"
                out(f"{REVERSE}  ► MY CALLSIGN : {val}{RESET}")
            else:
                cs_str = f"{GREEN_BG}{callsign}{RESET}" if callsign else f"{DIM}(not set){RESET}"
                out(f"    MY CALLSIGN : {cs_str}")

        elif item == "MY GRID":
            if settings_active == "locator":
                inp = locator_input.upper()
                valid = validate_locator(inp) if len(inp) >= 4 else None
                if valid is True:
                    field = f"{GREEN_BG} {inp}_ [OK]{RESET}"
                elif valid is False:
                    field = f"{RED_BG} {inp}_ [INVALID]{RESET}"
                else:
                    field = f"{GREEN_BG} {inp}_ {RESET}"
                out(f"{REVERSE}  ► MY GRID     : {field}")
            elif cursor:
                val = locator if locator else "(not set)"
                out(f"{REVERSE}  ► MY GRID     : {val}{RESET}")
            else:
                valid = validate_locator(locator) if locator else None
                if valid is True:
                    loc_str = f"{GREEN_BG}{locator}{RESET}"
                elif valid is False:
                    loc_str = f"{RED_BG}{locator}{RESET}"
                else:
                    loc_str = f"{DIM}(not set){RESET}"
                out(f"    MY GRID     : {loc_str}")

        elif item == "WSJT-X PORT":
            rtag = f"  {DIM}[restart required]{RESET}" if restart_required else ""
            if settings_active == "proxy_port":
                vld = validate_port(port_input) if port_input else None
                field = f"{RED_BG} {port_input}_ [1024-65535]{RESET}" if (port_input and not vld) else f"{GREEN_BG} {port_input}_ {RESET}"
                out(f"{REVERSE}  ► WSJT-X PORT : {field}")
            elif cursor:
                out(f"{REVERSE}  ► WSJT-X PORT : {proxy_port}{rtag}{RESET}")
            else:
                out(f"    WSJT-X PORT : {GREEN_BG}{proxy_port}{RESET}{rtag}")

        elif item == "SDR++ PORT":
            rtag = f"  {DIM}[restart required]{RESET}" if restart_required else ""
            if settings_active == "sdr_port":
                vld = validate_port(port_input) if port_input else None
                field = f"{RED_BG} {port_input}_ [1024-65535]{RESET}" if (port_input and not vld) else f"{GREEN_BG} {port_input}_ {RESET}"
                out(f"{REVERSE}  ► SDR++ PORT  : {field}")
            elif cursor:
                out(f"{REVERSE}  ► SDR++ PORT  : {sdr_port_setting}{rtag}{RESET}")
            else:
                out(f"    SDR++ PORT  : {GREEN_BG}{sdr_port_setting}{RESET}{rtag}")

    out()
    if settings_active:
        footer("Type port | Enter = SAVE | Esc = CANCEL", w)
    else:
        footer("↑↓ = NAVIGATE | Enter = SELECT | Esc = BACK", w)

    flush()

WELCOME_ITEMS = ["MY CALLSIGN", "MY GRID", "START"]

def render_welcome():
    w = width()

    sys.stdout.write(CLEAR)
    sys.stdout.write(HIDE_CUR)

    header("BANDHOPPER 1.0 by SQ5WBW & AI", w)
    out()
    out(f"  WELCOME")
    out()

    for i, item in enumerate(WELCOME_ITEMS):
        cursor = (i == settings_cursor)

        if item == "START":
            out()
            out(f"{REVERSE}  ► START{RESET}" if cursor else f"    START")

        elif item == "MY CALLSIGN":
            if settings_active == "callsign":
                inp = callsign_input.upper()
                out(f"{REVERSE}  ► MY CALLSIGN : {GREEN_BG} {inp}_ {RESET}")
            elif cursor:
                val = callsign if callsign else "(not set)"
                out(f"{REVERSE}  ► MY CALLSIGN : {val}{RESET}")
            else:
                cs_str = f"{GREEN_BG}{callsign}{RESET}" if callsign else f"{DIM}(not set){RESET}"
                out(f"    MY CALLSIGN : {cs_str}")

        elif item == "MY GRID":
            if settings_active == "locator":
                inp = locator_input.upper()
                valid = validate_locator(inp) if len(inp) >= 4 else None
                if valid is True:
                    field = f"{GREEN_BG} {inp}_ [OK]{RESET}"
                elif valid is False:
                    field = f"{RED_BG} {inp}_ [INVALID]{RESET}"
                else:
                    field = f"{GREEN_BG} {inp}_ {RESET}"
                out(f"{REVERSE}  ► MY GRID     : {field}")
            elif cursor:
                val = locator if locator else "(not set)"
                out(f"{REVERSE}  ► MY GRID     : {val}{RESET}")
            else:
                valid = validate_locator(locator) if locator else None
                if valid is True:
                    loc_str = f"{GREEN_BG}{locator}{RESET}"
                elif valid is False:
                    loc_str = f"{RED_BG}{locator}{RESET}"
                else:
                    loc_str = f"{DIM}(not set){RESET}"
                out(f"    MY GRID     : {loc_str}")

    out()
    if settings_active:
        footer("Type | Enter = SAVE | Esc = CANCEL", w)
    else:
        footer("↑↓ = NAVIGATE | Enter = SELECT | START = begin", w)

    flush()

# -------------------------
# RENDER: BAND HOP RULES
# -------------------------

def render_bandrules():
    w = width()

    sys.stdout.write(CLEAR)
    sys.stdout.write(HIDE_CUR)

    header("BANDHOPPER 1.0 by SQ5WBW & AI", w)
    out()
    col1_w = 28  # fixed: max band cell width (26) + 2 margin
    out(f"    {'BAND SELECTION':<{col1_w}}    NEXT HOP AFTER")
    out()

    eff_sel   = pending_rules_sel if pending_rules_sel is not None else selected_bands
    eff_rules = pending_rules     if pending_rules is not None else band_cycles

    for idx, (freq, label) in enumerate(BANDS_ALL):
        cursor    = (idx == bandrules_cursor)
        checked   = label in eff_sel
        cycles    = eff_rules.get(label, 10)
        total_sec = cycles * CYCLE_SECONDS
        secs_str  = fmt_cycle_time(total_sec)
        box       = "[#]" if checked else "[ ]"

        freq_str  = BAND_FREQ_LABEL.get(label, "")
        band_str  = f"{box} {label} ({freq_str})"

        # cycles column — prefix always 4 visible chars
        if cursor and bandrules_col == 1 and bandrules_editing:
            inp = bandrules_input
            try:
                val = int(inp) if inp else 0
                valid = 1 <= val <= 15
            except:
                valid = False
            if inp and not valid:
                cyc_str = f"{RED_BG}{inp}{RESET} {RED_BG}[1-15]{RESET}"
            else:
                cyc_str = f"{GREEN_BG}{inp}_{RESET}"
            cycles_col = f"  ► {cyc_str} FT8 CYCLE{'S' if cycles != 1 else ''}  {secs_str}"
        elif cursor and bandrules_col == 1:
            cycle_label = "FT8 CYCLE" if cycles == 1 else "FT8 CYCLES"
            cycles_col = f"{REVERSE}  ► {cycles:<2}  {cycle_label}  {secs_str}{RESET}"
        elif checked:
            cycle_label = "FT8 CYCLE" if cycles == 1 else "FT8 CYCLES"
            cycles_col  = f"    {REVERSE}{cycles:<2}  {cycle_label}  {secs_str}{RESET}"
        else:
            cycle_label = "FT8 CYCLE" if cycles == 1 else "FT8 CYCLES"
            cycles_col  = f"    {cycles:<2}  {cycle_label}  {secs_str}"

        if cursor and bandrules_col == 0:
            band_cell = f"{REVERSE}  ► {band_str}{RESET}"
        elif cursor and bandrules_col == 1:
            band_cell = f"    {GREEN_BG}{band_str}{RESET}" if checked else f"    {band_str}"
        elif checked:
            band_cell = f"    {GREEN_BG}{band_str}{RESET}"
        else:
            band_cell = f"    {band_str}"

        import re as _re
        def vis(s): return len(_re.sub(r'\033\[[^m]*m', '', s))
        pad = col1_w + 4 - vis(band_cell)
        out(band_cell + " " * max(1, pad) + cycles_col)

    out()
    out(f"{REVERSE}  ► BACK{RESET}" if bandrules_cursor == len(BANDS_ALL) else f"    BACK")
    out()
    if bandrules_editing:
        footer("Type [1-15] | Enter = SAVE | Esc = CANCEL", w)
    else:
        footer("←↑↓→ = NAVIGATE | Enter = SELECT | Esc = BACK", w)

    flush()

# -------------------------
# RENDER DISPATCHER
# -------------------------

def render():
    if ui_screen == UI_WELCOME:
        render_welcome()
    elif ui_screen == UI_DASHBOARD:
        render_dashboard()
    elif ui_screen == UI_MENU:
        render_menu()
    elif ui_screen == UI_MODE_SEL:
        render_mode_sel()
    elif ui_screen == UI_BANDRULES:
        render_bandrules()
    elif ui_screen == UI_BANDS:
        render_bands()
    elif ui_screen == UI_SETTINGS:
        render_settings()


# -------------------------
# INPUT HANDLING
# -------------------------

def flush_input():
    """Discard any buffered keypresses — prevents menu from 'running away'."""
    fd = sys.stdin.fileno()
    while select.select([sys.stdin], [], [], 0)[0]:
        os.read(fd, 32)

def read_key():
    fd = sys.stdin.fileno()
    ready = select.select([sys.stdin], [], [], 0.2)
    if not ready[0]:
        return None

    ch = os.read(fd, 1)

    if ch == b'\x03':
        return 'CTRL_C'

    if ch == b'\x1b':
        ready2 = select.select([sys.stdin], [], [], 0.05)
        if ready2[0]:
            rest = os.read(fd, 2)
            seq = ch + rest
            if seq == b'\x1b[A':
                flush_input()
                return 'UP'
            if seq == b'\x1b[B':
                flush_input()
                return 'DOWN'
            if seq == b'\x1b[C': return 'RIGHT'
            if seq == b'\x1b[D': return 'LEFT'
        return 'ESC'

    if ch in (b'\r', b'\n'):
        return 'ENTER'

    if ch == b'\x7f' or ch == b'\x08':
        return 'BACKSPACE'

    try:
        return ch.decode('utf-8')
    except:
        return None


def apply_mode(mode):
    """Apply a hopping mode change and reset band scanning."""
    global current_mode, band_index, cycle_counter, current_freq, current_label
    current_mode = mode
    band_index = 0
    cycle_counter = 0
    current_freq, current_label = get_band(band_index)
    sdr.send(f"F {current_freq}")
    save_settings()


def handle_key(key):
    global ui_screen, menu_cursor, mode_cursor, cycles_cursor, bands_cursor
    global settings_cursor, settings_active, settings_return, settings_return_mode, callsign_input, locator_input, callsign, locator, port_input, proxy_port, sdr_port_setting, restart_required
    global current_mode, pending_mode, pending_cycles, pending_bands, selected_bands
    global band_index, cycle_counter, current_freq, current_label, running, band_cycles
    global bandrules_cursor, bandrules_col, bandrules_editing, bandrules_input, pending_rules, pending_rules_sel

    if key is None:
        return

    if key == 'CTRL_C':
        running = False
        return

    # ---- WELCOME ----
    if ui_screen == UI_WELCOME:
        if settings_active == "callsign":
            if key == 'ESC':
                callsign_input = ""
                settings_active = None
            elif key == 'ENTER':
                callsign = callsign_input.upper().strip()
                callsign_input = ""
                settings_active = None
                save_settings()
            elif key == 'BACKSPACE':
                callsign_input = callsign_input[:-1]
            elif key and len(key) == 1 and key.isprintable():
                if len(callsign_input) < 12:
                    callsign_input += key.upper()
        elif settings_active == "locator":
            if key == 'ESC':
                locator_input = ""
                settings_active = None
            elif key == 'ENTER':
                inp = locator_input.upper().strip()
                if inp == "" or validate_locator(inp):
                    locator = inp
                    locator_input = ""
                    settings_active = None
                    save_settings()
            elif key == 'BACKSPACE':
                locator_input = locator_input[:-1]
            elif key and len(key) == 1 and key.isprintable():
                if len(locator_input) < 6:
                    locator_input += key.upper()
        else:
            if key == 'UP':
                settings_cursor = (settings_cursor - 1) % len(WELCOME_ITEMS)
            elif key == 'DOWN':
                settings_cursor = (settings_cursor + 1) % len(WELCOME_ITEMS)
            elif key == 'ENTER':
                selected = WELCOME_ITEMS[settings_cursor]
                if selected == "MY CALLSIGN":
                    callsign_input = callsign
                    settings_active = "callsign"
                elif selected == "MY GRID":
                    locator_input = locator
                    settings_active = "locator"
                elif selected == "START":
                    save_settings()
                    ui_screen = UI_DASHBOARD
        return

    # ---- DASHBOARD ----
    if ui_screen == UI_DASHBOARD:
        if key in ('m', 'M'):
            ui_screen = UI_MENU
            menu_cursor = 0

    # ---- MENU ----
    elif ui_screen == UI_MENU:
        if key == 'UP':
            menu_cursor = (menu_cursor - 1) % len(MENU_ITEMS)
        elif key == 'DOWN':
            menu_cursor = (menu_cursor + 1) % len(MENU_ITEMS)
        elif key in ('ENTER', 'ESC'):
            if key == 'ESC':
                ui_screen = UI_DASHBOARD
                return
            selected = MENU_ITEMS[menu_cursor]
            if selected == "AI HOPPING":
                ui_screen = UI_MODE_SEL
                pending_mode = current_mode
                mode_cursor = MODE_ITEMS.index(current_mode) if current_mode in MODE_ITEMS else 0
            elif selected == "BANDS":
                ui_screen = UI_BANDRULES
                pending_rules = {l: band_cycles.get(l, 10) for l in [b[1] for b in BANDS_ALL]}
                pending_rules_sel = set(selected_bands)
                bandrules_cursor = 0
                bandrules_col = 0
                bandrules_editing = False
                bandrules_input = ""

            elif selected == "SETTINGS":
                ui_screen = UI_SETTINGS
                settings_cursor = 0
            elif selected == "BACK":
                ui_screen = UI_DASHBOARD

    # ---- HOPPING MODE ----
    elif ui_screen == UI_MODE_SEL:
        if key == 'UP':
            mode_cursor = (mode_cursor - 1) % len(MODE_ITEMS)
        elif key == 'DOWN':
            mode_cursor = (mode_cursor + 1) % len(MODE_ITEMS)
        elif key in ('ENTER', 'ESC'):
            if key == 'ESC':
                if pending_mode and pending_mode != current_mode:
                    apply_mode(pending_mode)
                pending_mode = None
                ui_screen = UI_MENU
                return
            selected = MODE_ITEMS[mode_cursor]
            if selected == "BACK":
                if pending_mode and pending_mode != current_mode:
                    apply_mode(pending_mode)
                pending_mode = None
                ui_screen = UI_MENU
            else:
                if (selected == MODE_DAYNIGHT and not auto_available()) or                    (selected == MODE_GRAYLINE and not grayline_available()):
                    # redirect to SETTINGS with MY GRID active
                    settings_return_mode = selected
                    pending_mode = None
                    ui_screen = UI_SETTINGS
                    settings_cursor = 1  # MY GRID
                    settings_active = "locator"
                    settings_return = UI_MODE_SEL
                    locator_input = locator
                else:
                    pending_mode = selected

    # ---- FT8 CYCLES ----
    elif ui_screen == UI_CYCLES:
        CYCLES_TOTAL = CYCLES_MAX + 1  # 0-14 = cycles 1-15, 15 = BACK
        if key == 'UP':
            if cycles_cursor == CYCLES_MAX:  # BACK → go to 10 (last in left col)
                cycles_cursor = 9
            elif cycles_cursor >= 10:
                cycles_cursor -= 1
                if cycles_cursor < 10:
                    cycles_cursor = 9
            else:
                cycles_cursor = (cycles_cursor - 1) % 10
        elif key == 'DOWN':
            if cycles_cursor >= 10:
                if cycles_cursor < 14:
                    cycles_cursor += 1
                else:
                    cycles_cursor = CYCLES_MAX  # → BACK
            else:
                cycles_cursor = (cycles_cursor + 1) % 10
        elif key == 'LEFT':
            if cycles_cursor >= 10:
                cycles_cursor -= 10  # right col → left col same row
            elif cycles_cursor == CYCLES_MAX:
                cycles_cursor = 4   # BACK → left col row 5
        elif key == 'RIGHT':
            if cycles_cursor < 10:
                new = cycles_cursor + 10
                if new < CYCLES_MAX:
                    cycles_cursor = new
                else:
                    cycles_cursor = CYCLES_MAX  # → BACK
        elif key == 'ESC':
            if pending_cycles is not None and pending_cycles != CYCLE_LIMIT:
                CYCLE_LIMIT = pending_cycles
                cycle_counter = min(cycle_counter, CYCLE_LIMIT - 1)
                save_settings()
            pending_cycles = None
            ui_screen = UI_MENU
        elif key == 'ENTER':
            if cycles_cursor == CYCLES_MAX:  # BACK
                if pending_cycles is not None and pending_cycles != CYCLE_LIMIT:
                    CYCLE_LIMIT = pending_cycles
                    cycle_counter = min(cycle_counter, CYCLE_LIMIT - 1)
                    save_settings()
                pending_cycles = None
                ui_screen = UI_MENU
            else:
                pending_cycles = cycles_cursor + 1

    # ---- BAND SELECTION ----
    elif ui_screen == UI_BANDS:
        BANDS_TOTAL = len(BANDS_ALL) + 1
        BACK_IDX    = len(BANDS_ALL)
        if key == 'UP':
            bands_cursor = (bands_cursor - 1) % BANDS_TOTAL
        elif key == 'DOWN':
            bands_cursor = (bands_cursor + 1) % BANDS_TOTAL
        elif key in ('ENTER', 'ESC'):
            if key == 'ENTER' and bands_cursor != BACK_IDX:
                # toggle band
                label = BANDS_ALL[bands_cursor][1]
                if label in pending_bands:
                    if len(pending_bands) > 1:
                        pending_bands.discard(label)
                else:
                    pending_bands.add(label)
            else:
                # BACK or ESC — apply
                selected_bands = set(pending_bands)
                if len(selected_bands) == 1 and current_mode == MODE_DAYNIGHT:
                    current_mode = MODE_ALLBANDS
                if len(selected_bands) == 1 and current_mode == MODE_GRAYLINE:
                    current_mode = MODE_ALLBANDS
                band_index = 0
                cycle_counter = 0
                current_freq, current_label = get_band(band_index)
                sdr.send(f"F {current_freq}")
                pending_bands = None
                save_settings()
                ui_screen = UI_MENU

    # ---- BAND HOP RULES ----
    elif ui_screen == UI_BANDRULES:
        TOTAL = len(BANDS_ALL) + 1  # bands + BACK
        BACK_IDX = len(BANDS_ALL)

        if bandrules_editing:
            if key == 'ESC':
                bandrules_input = ""
                bandrules_editing = False
            elif key == 'ENTER':
                try:
                    val = int(bandrules_input)
                    if 1 <= val <= 15:
                        label = BANDS_ALL[bandrules_cursor][1]
                        pending_rules[label] = val
                        bandrules_input = ""
                        bandrules_editing = False
                except:
                    pass  # invalid — stay editing
            elif key == 'BACKSPACE':
                bandrules_input = bandrules_input[:-1]
            elif key and key.isdigit() and len(bandrules_input) < 2:
                bandrules_input += key
        else:
            if key == 'UP':
                if bandrules_cursor > 0:
                    bandrules_cursor -= 1
            elif key == 'DOWN':
                if bandrules_cursor < BACK_IDX:
                    bandrules_cursor += 1
            elif key == 'LEFT':
                bandrules_col = 0
            elif key == 'RIGHT':
                if bandrules_cursor < BACK_IDX:
                    bandrules_col = 1
            elif key == 'ENTER':
                if bandrules_cursor == BACK_IDX:
                    # apply and return
                    band_cycles = dict(pending_rules)
                    selected_bands = set(pending_rules_sel)
                    # reset if current band no longer active
                    if current_label not in selected_bands:
                        band_index = 0
                        cycle_counter = 0
                        current_freq, current_label = get_band(band_index)
                        sdr.send(f"F {current_freq}")
                    pending_rules = None
                    pending_rules_sel = None
                    save_settings()
                    ui_screen = UI_MENU
                elif bandrules_col == 0:
                    # toggle band selection
                    label = BANDS_ALL[bandrules_cursor][1]
                    if label in pending_rules_sel:
                        if len(pending_rules_sel) > 1:
                            pending_rules_sel.discard(label)
                    else:
                        pending_rules_sel.add(label)
                else:
                    # start editing cycles
                    label = BANDS_ALL[bandrules_cursor][1]
                    bandrules_input = str(pending_rules.get(label, 10))
                    bandrules_editing = True
            elif key == 'ESC':
                # apply and return — same as BACK
                band_cycles = dict(pending_rules)
                selected_bands = set(pending_rules_sel)
                if current_label not in selected_bands:
                    band_index = 0
                    cycle_counter = 0
                    current_freq, current_label = get_band(band_index)
                    sdr.send(f"F {current_freq}")
                pending_rules = None
                pending_rules_sel = None
                save_settings()
                ui_screen = UI_MENU

    # ---- SETTINGS ----
    elif ui_screen == UI_SETTINGS:
        if settings_active == "callsign":
            if key == 'ESC':
                callsign_input = ""
                settings_active = None
            elif key == 'ENTER':
                callsign = callsign_input.upper().strip()
                callsign_input = ""
                settings_active = None
                save_settings()
            elif key == 'BACKSPACE':
                callsign_input = callsign_input[:-1]
            elif key and len(key) == 1 and key.isprintable():
                if len(callsign_input) < 12:
                    callsign_input += key.upper()

        elif settings_active == "locator":
            if key == 'ESC':
                locator_input = ""
                settings_active = None
            elif key == 'ENTER':
                inp = locator_input.upper().strip()
                if inp == "" or validate_locator(inp):
                    old_locator = locator
                    locator = inp
                    locator_input = ""
                    settings_active = None
                    if not locator_set() and current_mode in (MODE_DAYNIGHT, MODE_GRAYLINE):
                        apply_mode(MODE_ALLBANDS)
                    elif locator != old_locator:
                        band_index = 0
                        cycle_counter = 0
                        current_freq, current_label = get_band(band_index)
                        sdr.send(f"F {current_freq}")
                    save_settings()
            elif key == 'BACKSPACE':
                locator_input = locator_input[:-1]
            elif key and len(key) == 1 and key.isprintable():
                if len(locator_input) < 6:
                    locator_input += key.upper()

        elif settings_active in ("proxy_port", "sdr_port"):
            if key == 'ESC':
                port_input = ""
                settings_active = None
            elif key == 'ENTER':
                if validate_port(port_input):
                    val = int(port_input)
                    if settings_active == "proxy_port":
                        proxy_port = val
                    else:
                        sdr_port_setting = val
                    port_input = ""
                    settings_active = None
                    restart_required = True
                    save_settings()
            elif key == 'BACKSPACE':
                port_input = port_input[:-1]
            elif key and key.isdigit() and len(port_input) < 5:
                port_input += key

        else:
            if key == 'UP':
                settings_cursor = (settings_cursor - 1) % len(SETTINGS_NAV)
            elif key == 'DOWN':
                settings_cursor = (settings_cursor + 1) % len(SETTINGS_NAV)
            elif key == 'ESC':
                dest = settings_return
                settings_return = UI_MENU
                if dest == UI_MODE_SEL:
                    pending_mode = settings_return_mode if settings_return_mode else current_mode
                    mode_cursor = MODE_ITEMS.index(pending_mode) if pending_mode in MODE_ITEMS else 0
                    settings_return_mode = None
                ui_screen = dest
            elif key == 'ENTER':
                selected = SETTINGS_NAV[settings_cursor]
                if selected == "MY CALLSIGN":
                    callsign_input = callsign
                    settings_active = "callsign"
                elif selected == "MY GRID":
                    locator_input = locator
                    settings_active = "locator"
                elif selected == "WSJT-X PORT":
                    port_input = str(proxy_port)
                    settings_active = "proxy_port"
                elif selected == "SDR++ PORT":
                    port_input = str(sdr_port_setting)
                    settings_active = "sdr_port"
                elif selected == "BACK":
                    dest = settings_return
                    settings_return = UI_MENU
                    if dest == UI_MODE_SEL:
                        pending_mode = settings_return_mode if settings_return_mode else current_mode
                        mode_cursor = MODE_ITEMS.index(pending_mode) if pending_mode in MODE_ITEMS else 0
                        settings_return_mode = None
                    ui_screen = dest

# -------------------------
# PROXY
# -------------------------

def handle(conn):
    global wsjtx_last_seen
    with conn:
        while running:
            try:
                data = conn.recv(1024)
                if not data:
                    break
                cmd = data.decode().strip()
                if cmd == "f":
                    wsjtx_last_seen = time.time()
                    resp = str(current_freq)
                else:
                    resp = sdr.send(cmd)
                conn.sendall((resp + "\n").encode())
            except:
                break

# -------------------------
# TMUX AUTO-SESSION
# -------------------------

def ensure_tmux():
    """If not running inside tmux, relaunch inside a new tmux session."""
    if os.environ.get('TMUX'):
        return  # already inside tmux — nothing to do

    # check if tmux is available
    import shutil as _shutil
    if not _shutil.which('tmux'):
        return  # run normally without tmux

    session = "bhop"
    script  = os.path.abspath(__file__)
    os.system(f"tmux kill-session -t {session} 2>/dev/null")
    # create session in background, set options, then attach
    os.system(f"tmux new-session -d -s {session} '{sys.executable} {script}'")
    os.system(f"tmux set-option -t {session} status off")
    os.system(f"tmux attach-session -t {session}")
    os.system("clear")
    sys.exit(0)

# -------------------------
# MAIN
# -------------------------

def main():
    global running

    ensure_tmux()

    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, proxy_port))
    server.listen(10)
    server.settimeout(0.5)

    init()
    threading.Thread(target=engine, daemon=True).start()

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setraw(fd)

    try:
        while running:
            try:
                conn, _ = server.accept()
                threading.Thread(target=handle, args=(conn,), daemon=True).start()
            except:
                pass

            key = read_key()
            handle_key(key)

            if not running:
                break

            render()

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write(RESET)
        sys.stdout.write(SHOW_CUR)
        sys.stdout.write(CLEAR)
        farewell = f" BANDHOPPER DOWN — QRT, see you next time {callsign}, 73!" if callsign else " BANDHOPPER DOWN — QRT, 73!"
        sys.stdout.write(f"{farewell}\r\n\r\n")
        sys.stdout.flush()
        # spawn background process to kill tmux session after farewell is visible
        os.system("tmux set-option -t bhop remain-on-exit off 2>/dev/null")
        threading.Thread(
            target=lambda: (time.sleep(2), os.system("tmux kill-session -t bhop 2>/dev/null")),
            daemon=True
        ).start()
        time.sleep(2)

if __name__ == "__main__":
    main()