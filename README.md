# Tail Gate RG — Automated Dog Door

A solar-powered dog door controlled by a Raspberry Pi Zero 2 W. Owners can control the door remotely via an iOS app or home screen widget or use a physical hardware switch to open/close the door.

---

## Features

- **Remote control** — iOS app and home screen widget with live door status
- **Owner availability** — each owner can toggle their availability; door only opens when both are available
- **Push notifications** — alerts when the door opens or closes
- **LED status panel** — 5 indicator lights show door state, motion, countdown, and owner availability
- **Manual override** — physical 3-position toggle switch works regardless of owner availability
- **Emergency stop** — app button halts door mid-movement
- **OLED display** — live door state, open %, owner availability, current IP address to confirm network connectivity
- **Buzzer** — audio feedback on open/close/stuck events
- **Physical buttons** — restart service (1s hold), reboot Pi (3s hold), shutdown (both buttons 2s hold); all with OLED animations and countdown cancellation
- **Solar powered** — 30W panel, MPPT charge controller, 12V 7Ah SLA battery
- **Firebase backend** — real-time sync between Pi and app via Firebase Realtime Database

---

## Repository Structure

```
dog-door/
├── door_controller.py      # Main Pi controller script
├── dog-door.service        # systemd service unit
├── deploy-to-pi.sh         # Mac: copies all files to Pi after reflash
├── setup-pi.sh             # Pi: installs deps, service, I2C after reflash
├── WIRING.md               # Full GPIO pin assignments and wiring diagrams
├── PARTS.md                # Bill of materials with purchase links
├── RFID_TAGS.md            # Tag IDs and reader assignments
└── app/                    # React Native iOS app (Expo SDK 54)
    ├── App.js              # Main app UI
    ├── firebase.js         # Firebase initialization
    ├── app.json            # Expo config
    ├── eas.json            # EAS Build config
    └── targets/
        └── widget/         # iOS home screen widget (WidgetKit/SwiftUI)
            ├── DogDoorWidget.swift
            └── expo-target.config.js
```

---

## Hardware Overview

| Component | Part |
|---|---|
| Controller | Raspberry Pi Zero 2 W + PiZ-EzConnect screw terminal breakout |
| Motor driver | L298N dual H-bridge |
| Actuator | 12V linear actuator, 4" stroke, 14mm/s, 220 lb force |
| RFID readers | 2× MFRC522 (SPI, one per side of door) — deferred, range insufficient |
| RFID tags | 13.56 MHz Mifare collar tags |
| Power | 30W solar panel, 10A MPPT charge controller, 12V 7Ah SLA battery |
| Pi power | DROK buck converter (12V → 5V) |
| Enclosures | 2× TICONN IP67 8.7"×6.7"×4.3" weatherproof boxes |
| LEDs | 5× Gebildet 12-24V panel indicators (green/red/amber/blue/white) |
| Transistors | 2N2222 NPN (one per LED) |
| OLED display | 0.96" SSD1306 I2C (128×64) |
| Buzzer | Passive buzzer on GPIO23 |
| Buttons | 2× tactile pushbuttons (restart + reboot/shutdown) |
| Perfboard | 70×90mm perfboard with LED driver circuits, buzzer, OLED, buttons |
| Speaker | MAX98357A I2S amplifier (future) |

See [PARTS.md](PARTS.md) for full bill of materials and purchase links.

> **Note:** The MFRC522 readers have a read range of ~1–5 cm, which is marginal for medium-sized dogs approaching the door. A UHF RFID solution (SparkFun M6E Nano + dual external patch antennas) is planned as a replacement for reliable 0.5–2 meter detection.

---

## System Architecture

```
Solar panel
    │
    ▼
MPPT charge controller ──→ 12V SLA battery
                                │
                    ┌───────────┴──────────┐
                    ▼                       ▼
             Buck converter            L298N driver
             (12V → 5V)                     │
                    │                  Linear actuator
                    ▼
           Raspberry Pi Zero 2 W
                    │
        ┌───────────┼────────────┐
        ▼           ▼            ▼
   MFRC522 ×2   5× LEDs    MAX98357A
   (SPI)    (2N2222 NPN)   (I2S speaker)
                    │
                    ▼
            Firebase Realtime DB
                    │
            ┌───────┴────────┐
            ▼                ▼
         iOS App        Home screen widget
```

---

## Pi Setup

### Quick setup after reflashing

Two scripts handle the full setup workflow:

**1. On your Mac** — copies all files to the Pi (grabs the latest Firebase key from `~/Downloads` automatically):
```bash
chmod +x deploy-to-pi.sh
./deploy-to-pi.sh
```

**2. On the Pi** — installs dependencies, sets up the venv, installs and starts the service:
```bash
ssh pat0222@dogdoorpi.local './setup-pi.sh'
```

When reflashing, use Raspberry Pi Imager with:
- **Device:** Raspberry Pi Zero 2 W
- **OS:** Raspberry Pi OS Lite (64-bit)
- **WiFi SSID:** CerberusIoT24 (2.4GHz — Pi Zero 2 W does not support 5GHz)
- **Hostname:** dogdoorpi
- **Username:** pat0222
- **Enable SSH:** yes (password authentication)

### Firebase service account

Download the Firebase Admin SDK service account key from the Firebase console and save it to:

```
/home/pat0222/dog-door/firebase-key.json
```

This file is in `.gitignore` and must never be committed.

### Configuration

Edit `door_controller.py` to set your RFID tag IDs:

```python
AUTHORIZED_TAGS   = {613025449752, 372068189196}
READER1_HOME_TAG  = 613025449752   # tag assigned to Reader 1 side
READER2_HOME_TAG  = 372068189196   # tag assigned to Reader 2 side
```

See [RFID_TAGS.md](RFID_TAGS.md) for tag identification instructions.

### Running manually

```bash
cd /home/pat0222/dog-door
source venv/bin/activate
python door_controller.py
```

### Running as a systemd service

```bash
sudo cp dog-door.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable dog-door
sudo systemctl start dog-door

# Useful commands
sudo systemctl restart dog-door
sudo journalctl -u dog-door -f
```

---

## GPIO Pin Assignments

| GPIO | Pin | Function |
|---|---|---|
| GPIO2 | 3 | OLED SDA (I2C) |
| GPIO3 | 5 | OLED SCL (I2C) |
| GPIO5 | 29 | Manual switch SW_OPEN |
| GPIO6 | 31 | Manual switch SW_CLOSE |
| GPIO12 | 32 | LED green (door open) |
| GPIO13 | 33 | LED red (door closed) |
| GPIO16 | 36 | LED amber (close countdown) |
| GPIO17 | 11 | L298N IN1 |
| GPIO20 | 38 | LED blue (Rita available) |
| GPIO22 | 15 | L298N ENA |
| GPIO23 | 16 | Passive buzzer (PWM) |
| GPIO24 | 18 | BTN_RESTART |
| GPIO25 | 22 | BTN_REBOOT/shutdown |
| GPIO26 | 37 | LED white (Ginger available) |
| GPIO27 | 13 | L298N IN2 |

---

## Physical Buttons

| Action | Result |
|---|---|
| Hold BTN_RESTART 1s | Scrolls "RESTARTING DOG DOOR SERVICE" → restarts service |
| Hold BTN_REBOOT 3s | "REBOOTING PI IN" scroll → 5–1 countdown → mushroom cloud → reboot |
| Press BTN_REBOOT during reboot countdown | "REBOOT CANCELLED" — aborts reboot |
| Hold both buttons 2s | "SHUTTING DOWN IN" scroll → 5–1 countdown → poop emoji → shutdown |
| Press either button during shutdown countdown | "SHUTDOWN CANCELLED" — aborts shutdown |

---

## OLED Display

The 128×64 SSD1306 display shows live status updated every second:

```
CLOSED
Open: 0%
Owners: both
IP: x.x.x.x
```

I2C must be enabled on the Pi: `sudo raspi-config nonint do_i2c 0`

---

## LED Status Reference

| Pattern | Meaning |
|---|---|
| Green solid | Door open |
| Green flashing | Door opening |
| Red solid | Door closed |
| Red flashing | Door closing |
| Amber solid | Close countdown in progress |
| Blue solid | Rita available |
| White solid | Ginger available |
| Green + amber + red flashing together | Door stuck in partial state 15+ minutes |
| All 5 LEDs chasing in sequence | Firebase unreachable |

The chase pattern is suppressed for the first 5 seconds after startup to allow Firebase to connect.

---

## Firebase Setup

1. Create a Firebase project at [console.firebase.google.com](https://console.firebase.google.com)
2. Enable **Realtime Database** and **Anonymous Authentication**
3. Set database rules:

```json
{
  "rules": {
    "door":        { ".read": true,          ".write": "auth != null" },
    "owners":      { ".read": true,          ".write": "auth != null" },
    "command":     { ".read": "auth != null", ".write": "auth != null" },
    "push_tokens": { ".read": "auth != null", ".write": "auth != null" }
  }
}
```

4. Download the Admin SDK service account key for the Pi (see Pi Setup above)
5. Copy `firebase.js` config values from the Firebase console into `app/firebase.js`

---

## iOS App Setup

### Requirements

- Node.js 18+
- Expo CLI: `npm install -g expo`
- EAS CLI: `npm install -g eas-cli`
- Expo account at [expo.dev](https://expo.dev)
- Apple Developer Program membership (for TestFlight/App Store)

### Development

```bash
cd app
npm install --legacy-peer-deps
npx expo start
```

### Building for TestFlight

```bash
eas build --platform ios --profile production
eas submit --platform ios --latest
```

Build numbers are auto-incremented remotely — no manual version management needed.

### Home screen widget

The iOS widget (iOS 17+) is built with WidgetKit/SwiftUI and lives in `app/targets/widget/`. It is included automatically in EAS builds via the `@bacons/apple-targets` config plugin. The widget:

- Polls Firebase REST API every 30 seconds for door state and owner availability
- Sends open/close commands via Firebase REST API using a cached anonymous auth token
- Requires iOS 17+ for interactive (tappable) buttons

---

## Future RFID Door Logic

```
Both dogs detected on opposite sides
        │
        ▼
   Door opens
        │
        ▼ (10 second countdown)
   Dogs return home?
   ├── Yes → Door closes, push notification sent
   └── No  → Door closes anyway after timeout
```

- The door only opens automatically when **both owner availability toggles are on**
- The manual switch and override button work **regardless** of owner availability
- App open/close commands also bypass the owner availability check for Close

---

## Power Budget (approximate)

| Component | Draw |
|---|---|
| Pi Zero 2 W (idle) | ~120 mA @ 5V |
| L298N + actuator (moving) | 2–5 A @ 12V (brief) |
| RFID readers × 2 | ~50 mA @ 3.3V |
| LEDs × 5 | ~20 mA each @ 12V |
| Total idle | ~1–2 W |

30W panel + 7Ah battery provides ~3–4 days of backup with no sun.

---

## Planned Improvements

- [ ] Add neighbor as TestFlight tester
- [ ] Apple Watch app
- [ ] Replace MFRC522 readers with UHF RFID (R200-based module + patch antennas) for reliable medium-dog detection at 0.5–2 meter range
