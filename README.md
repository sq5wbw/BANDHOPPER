# BANDHOPPER 1.0
### Automated FT8 Band-Hopping Controller for WSJT-X & SDR++

**by SQ5WBW & AI**

---

## What is BANDHOPPER?

BANDHOPPER is an automated band-hopping controller designed for FT8 digital mode enthusiasts — both licensed amateur radio operators and SWL (shortwave listeners) who enjoy decoding digital emissions.

The application acts as a CAT proxy between WSJT-X and SDR++, automatically switching bands to capture as many stations as possible across selected frequency bands. Perfect for leaving your Raspberry Pi running 24/7 and checking [PSK Reporter](https://pskreporter.info) in the morning to see which stations were decoded overnight.

---

## Requirements

- Raspberry Pi (or any Linux system)
- Python 3
- [SDR++](https://www.sdrpp.org)
- [WSJT-X](https://wsjt.sourceforge.io)
- tmux — `sudo apt install tmux` *(recommended for background operation)*

---

## Quick Start

```bash
python3 bandhopper.py
```

---

## Running in Background with tmux

tmux allows BANDHOPPER to keep running after you close your SSH session.

**First launch:**
```bash
tmux new -s bhop
python3 bandhopper.py
```
Press `Ctrl+B`, then `D` to detach — BANDHOPPER keeps running in the background.

**Reconnect from SSH at any time:**
```bash
tmux attach -t bhop
```

**Check if BANDHOPPER is running:**
```bash
tmux ls
```

**Stop BANDHOPPER:**
```bash
tmux kill-session -t bhop
```

**Auto-start on Raspberry Pi boot:**
```bash
crontab -e
```
Add this line:
```
@reboot tmux new-session -d -s bhop 'python3 /home/pi/bandhopper.py'
```

---

## SDR++ Configuration

Enable **Rigctl Server** in SDR++:

| Setting | Value |
|---------|-------|
| Host | `127.0.0.1` |
| Port | `4532` |
| Tuning on startup | ✅ |
| Listening on startup | ✅ |

---

## WSJT-X Configuration

| Setting | Value |
|---------|-------|
| Rig | `AirspySDR#/predict` |
| CAT Control | `127.0.0.1` port `4533` |

---

## Features

### 🌅 AI HOPPING — DAY/NIGHT
Automatic band switching based on real sunrise/sunset calculation using the NOAA algorithm and your Maidenhead grid locator. No fixed UTC boundaries — true propagation-aware switching for your exact location.

### 🌄 DAY/NIGHT+GRAYLINE
Extended mode that expands to all selected bands during gray line windows (±30 min around sunrise/sunset) to capture rare DX propagation openings. Includes a real-time countdown to the next gray line event.

### 📻 BAND HOP RULES
Per-band FT8 cycle configuration. Each band can have its own number of FT8 cycles (1–15) before hopping to the next band. Prioritize your favourite bands with more time, reduce time on others. Time per band is calculated and displayed automatically.

### ⚙️ SETTINGS
- **MY CALLSIGN** — Your amateur radio callsign
- **MY GRID** — Maidenhead grid locator (required for DAY/NIGHT and GRAYLINE modes)
- **WSJT-X PORT** — Proxy server port (default: 4533)
- **SDR++ PORT** — Rigctl server port (default: 4532)

### 💾 Persistent Settings
All settings saved automatically to `bandhopper_settings.json` in the application folder.

### 🔌 CAT Proxy Server
Transparent proxy between WSJT-X and SDR++. WSJT-X always reports the correct frequency. Band hopping starts only after both WSJT-X and SDR++ are connected.

---

## Navigation

| Key | Action |
|-----|--------|
| `m` | Open menu |
| `↑` `↓` | Navigate |
| `←` `→` | Switch columns (BAND HOP RULES) |
| `Enter` | Select / Toggle |
| `Esc` | Back |
| `Ctrl+C` | Quit |

---

## Supported Bands

| Band | Frequency |
|------|-----------|
| 160m | 1.840 MHz |
| 80m | 3.573 MHz |
| 40m | 7.074 MHz |
| 30m | 10.136 MHz |
| 20m | 14.074 MHz |
| 17m | 18.100 MHz |
| 15m | 21.074 MHz |
| 12m | 24.915 MHz |
| 10m | 28.074 MHz |
| 6m EU | 50.313 MHz |
| 6m NA | 50.323 MHz |
| 4m | 70.154 MHz |
| 2m | 144.174 MHz |

---

*If you enjoy BANDHOPPER, consider buying me a coffee:*
**[buycoffee.to/sq5wbw](https://buycoffee.to/sq5wbw)**
