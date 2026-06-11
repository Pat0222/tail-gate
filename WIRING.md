# Dog Door Wiring Guide

## Bench Test Setup
- Power the Pi via USB (5V micro USB) — do NOT use the buck converter yet
- Power the L298N and actuator from a separate 12V supply
- Use breadboard for all low-voltage components (RFID readers, button, MAX98357A)
- Connect the actuator directly to L298N output terminals (not through breadboard)

---

## GPIO Pin Assignments

| GPIO | Physical Pin | Connected To |
|---|---|---|
| 3.3V | Pin 1 | RFID reader VCC (both), MAX98357A VDD |
| 5V | Pin 2 | L298N logic VCC |
| GPIO8 (CE0) | Pin 24 | RFID reader 1 — SDA (CS) |
| GPIO7 (CE1) | Pin 26 | RFID reader 2 — SDA (CS) |
| GPIO9 (MISO) | Pin 21 | Both RFID readers — MISO |
| GPIO10 (MOSI) | Pin 19 | Both RFID readers — MOSI |
| GPIO11 (SCLK) | Pin 23 | Both RFID readers — SCK |
| GPIO17 | Pin 11 | L298N — IN1 |
| GPIO18 | Pin 12 | MAX98357A — BCLK |
| GPIO19 | Pin 35 | MAX98357A — LRC |
| GPIO21 | Pin 40 | MAX98357A — DIN |
| GPIO22 | Pin 15 | L298N — ENA |
| GPIO5  | Pin 29 | Manual switch — open (+VE Load) |
| GPIO6  | Pin 31 | Manual switch — close (-VE Load) |
| GPIO12 | Pin 32 | LED green (open) — via 2N2222 transistor |
| GPIO13 | Pin 33 | LED red (closed) — via 2N2222 transistor |
| GPIO16 | Pin 36 | LED amber (countdown) — via 2N2222 transistor |
| GPIO20 | Pin 38 | LED blue (Rita available) — via 2N2222 transistor |
| GPIO26 | Pin 37 | LED white (Ginger available) — via 2N2222 transistor |
| GPIO23 | Pin 16 | Override pushbutton |
| GPIO24 | Pin 18 | RFID reader 2 — RST |
| GPIO25 | Pin 22 | RFID reader 1 — RST |
| GPIO27 | Pin 13 | L298N — IN2 |
| GND | Pin 6, 9, 14, 20, 25, 30, 34, 39 | Common ground |

---

## Component Wiring

### RFID Reader 1 (MFRC522) — Door Side A
| Reader Pin | Connects To |
|---|---|
| VCC | Pi 3.3V (Pin 1) |
| GND | Pi GND |
| RST | Pi GPIO25 (Pin 22) |
| SDA | Pi GPIO8/CE0 (Pin 24) |
| SCK | Pi GPIO11/SCLK (Pin 23) |
| MOSI | Pi GPIO10/MOSI (Pin 19) |
| MISO | Pi GPIO9/MISO (Pin 21) |
| IRQ | Not connected |

### RFID Reader 2 (MFRC522) — Door Side B
| Reader Pin | Connects To |
|---|---|
| VCC | Pi 3.3V (Pin 1) |
| GND | Pi GND |
| RST | Pi GPIO24 (Pin 18) |
| SDA | Pi GPIO7/CE1 (Pin 26) |
| SCK | Pi GPIO11/SCLK (Pin 23) — shared with reader 1 |
| MOSI | Pi GPIO10/MOSI (Pin 19) — shared with reader 1 |
| MISO | Pi GPIO9/MISO (Pin 21) — shared with reader 1 |
| IRQ | Not connected |

⚠️ MFRC522 is 3.3V only — do NOT connect VCC to 5V or you will damage the reader.

### L298N Motor Driver (Linear Actuator)
| L298N Pin | Connects To |
|---|---|
| IN1 | Pi GPIO17 (Pin 11) |
| IN2 | Pi GPIO27 (Pin 13) |
| ENA | Pi GPIO22 (Pin 15) |
| IN3, IN4, ENB | Not connected |
| +12V | 12V power supply positive |
| GND | 12V power supply negative + Pi GND |
| 5V (output) | Not used — Pi powered via USB |
| OUT1 | Actuator wire 1 |
| OUT2 | Actuator wire 2 |

**Actuator logic:**
| IN1 | IN2 | ENA | Result |
|---|---|---|---|
| HIGH | LOW | HIGH | Extend (door closes) |
| LOW | HIGH | HIGH | Retract (door opens) |
| LOW | LOW | HIGH | Stop |
| X | X | LOW | Stop |

### MAX98357A I2S Amplifier (Speaker)
| Amplifier Pin | Connects To |
|---|---|
| VDD | Pi 3.3V (Pin 1) |
| GND | Pi GND |
| DIN | Pi GPIO21 (Pin 40) |
| BCLK | Pi GPIO18 (Pin 12) |
| LRC | Pi GPIO19 (Pin 35) |
| SD | Not connected |
| GAIN | Not connected (default 9dB) |
| Speaker+ | Speaker + terminal |
| Speaker- | Speaker - terminal |

### Manual Reversing Switch (from actuator kit)
Repurposed as a 3.3V signal switch — do NOT connect to 12V.

| Switch Terminal | Connects To |
|---|---|
| +VE | Pi 3.3V (Pin 1) |
| -VE | Pi GND (Pin 6) |
| +VE(Load) | Pi GPIO5 (Pin 29) — open signal |
| -VE(Load) | Pi GPIO6 (Pin 31) — close signal |

- Center position: both GPIO5 and GPIO6 LOW — no action
- Open position: GPIO5 HIGH → door opens (if closed)
- Close position: GPIO6 HIGH → door closes (if open)
- Pull-down resistors configured in software — no external resistors needed

### LED Status Lights (via 2N2222 NPN Transistors)
Each LED uses the same circuit — repeat for green (GPIO12), red (GPIO13), amber (GPIO16):

```
Pi GPIO ──→ 1kΩ resistor ──→ 2N2222 Base (pin 2)
                              2N2222 Collector (pin 3) ──→ LED negative (cathode)
                              2N2222 Emitter (pin 1)  ──→ GND
12V ──────────────────────────────────────────────────→ LED positive (anode)
```

| GPIO | LED Color | Meaning |
|---|---|---|
| GPIO12 (Pin 32) | Green | Solid: door open. Flashing: opening |
| GPIO13 (Pin 33) | Red | Solid: door closed. Flashing: closing |
| GPIO16 (Pin 36) | Amber | Close countdown in progress |
| GPIO20 (Pin 38) | Blue | Rita available |
| GPIO26 (Pin 37) | White | Ginger available |

⚠️ The LEDs are 12-24V rated — do NOT connect directly to Pi GPIO (3.3V). The transistor switches the 12V side; the Pi only drives the base through the 1kΩ resistor.
⚠️ 2N2222 pin order (TO-92 package, flat side facing you): Emitter | Base | Collector (left to right).

### Override Pushbutton
| Connection | Connects To |
|---|---|
| One terminal | Pi GPIO23 (Pin 16) |
| Other terminal | Pi GND |

Use Pi's internal pull-up resistor in software — no external resistor needed.

---

## Full Power Architecture

### Bench Testing
```
USB (5V) ──────────────────────────→ Pi Zero 2 W (micro USB)
12V supply ────→ L298N +12V input
               └→ L298N GND ──────→ Pi GND (common ground)
```

### Final Installation
```
Solar panel ──→ Charge controller ──→ 12V SLA battery
                                         │
                              ┌──────────┴──────────┐
                              ↓                      ↓
                        Buck converter          L298N +12V
                        (set to 5V)                  │
                              │                 Linear actuator
                              ↓
                        Pi Zero 2 W
```

---

## Notes
- Solder the 2×20 header onto the Pi Zero 2 W first, then assemble the PiZ-EzConnect terminal blocks onto the board
- The PiZ-EzConnect plugs onto the Pi's GPIO header and provides screw terminals for the odd numbered pins — use these instead of jumper wires for the final installation
- For bench testing, jumper wires into the PiZ-EzConnect terminals work fine
- Set the buck converter output to exactly 5V with a multimeter before connecting the Pi
- The reverse polarity switch controller that came with the actuator is bypassed entirely — set it aside
- Test each component individually before wiring everything together
