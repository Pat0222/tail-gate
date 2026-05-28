# Puppy Play Time — Automated Dog Door

A solar-powered, RFID-triggered dog door controlled by a Raspberry Pi Zero 2 W. Dogs wear RFID collar tags; when both are detected on opposite sides of the fence simultaneously, the door opens automatically. Owners can also control the door remotely via an iOS app or home screen widget.

---

## Features

- **Automatic open/close** — triggered when both dogs are detected on opposite sides of the fence
- **Auto-close countdown** — door closes automatically after 10 seconds once the dogs are back
- **Remote control** — iOS app and home screen widget with live door status
- **Owner availability** — each owner can toggle their availability; door only opens automatically when both are available
- **Push notifications** — alerts when the door opens, closes, or the dogs come home
- **LED status panel** — 5 indicator lights show door state, motion, countdown, and owner availability
- **Manual override** — physical switch and override pushbutton work regardless of owner availability
- **Emergency stop** — app button halts door mid-movement
- **Solar powered** — 30W panel, MPPT charge controller, 12V 7Ah SLA battery
- **Firebase backend** — real-time sync between Pi and app via Firebase Realtime Database

---

## Repository Structure

```
dog-door/
├── door_controller.py      # Main Pi controller script
├── dog-door.service        # systemd service unit
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
| RFID readers | 2× MFRC522 (SPI, one per side of door) |
| RFID tags | 13.56 MHz Mifare collar tags |
| Power | 30W solar panel, 10A MPPT charge controller, 12V 7Ah SLA battery |
| Pi power | DROK buck converter (12V → 5V) |
| Enclosures | 2× TICONN IP67 8.7"×6.7"×4.3" weatherproof boxes |
| LEDs | 5× Gebildet 12-24V panel indicators (green/red/amber/blue/white) |
| Transistors | 2N2222 NPN (one per LED) |
| Speaker | MAX98357A I2S amplifier |

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

### Prerequisites

```bash
# Raspberry Pi OS Lite (64-bit), SSH enabled
# SPI enabled via raspi-config → Interface Options → SPI

pip install RPi.GPIO mfrc522 firebase-admin
```

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

See [WIRING.md](WIRING.md) for the full pin table and wiring diagrams. Key assignments:

| GPIO | Function |
|---|---|
| GPIO17, GPIO27 | L298N IN1, IN2 (actuator direction) |
| GPIO22 | L298N ENA (actuator enable) |
| GPIO8, GPIO7 | RFID reader 1, 2 SDA (SPI CE0/CE1) |
| GPIO5, GPIO6 | Manual switch open/close |
| GPIO23 | Override pushbutton |
| GPIO12 | LED green (door open) |
| GPIO13 | LED red (door closed) |
| GPIO16 | LED amber (close countdown) |
| GPIO20 | LED blue (Rita available) |
| GPIO26 | LED white (Ginger available) |

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

## Door Logic

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

- [ ] Replace MFRC522 readers with SparkFun M6E Nano UHF RFID module + dual external weatherproof patch antennas for reliable medium-dog detection at 0.5–2 meter range
- [ ] Mount components in two TICONN IP67 enclosures (electronics + power)
- [ ] Apple Watch app
- [ ] Add MAX98357A amplifier and speaker for audio alerts
- [ ] Add neighbor as TestFlight tester
