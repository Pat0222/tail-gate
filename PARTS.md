# Dog Door Parts List

Estimated total: ~$210–235

## Controller
| Part | Qty | Est. Cost | Notes |
|---|---|---|---|
| Raspberry Pi Zero 2 W | 1 | ✓ purchased | Header soldered manually — included in PiZ-EzConnect kit |
| PiZ-EzConnect Kit | 1 | ✓ purchased | GPIO screw terminal breakout board for Pi Zero. Includes 2×20 header. See alchemy-power.com/piz-ezconnect-kit/ |
| 32GB microSD card | 1 | ✓ purchased | |
| TICONN 2PK IP67 Weatherproof Enclosure (Off-White, 8.7"×6.7"×4.3") | 2 | ✓ purchased | One for Pi + wiring, one for battery + charge controller. Includes cable glands. Search B0GS4NL1LN on Amazon. |

## RFID
| Part | Qty | Est. Cost | Notes |
|---|---|---|---|
| AITIAO MFRC522 RFID Reader Kit (4-pack) | 2 | ✓ purchased | One reader per side of door. Includes S50 white cards and key fobs. |
| 13.56 MHz RFID pet collar tags | 2 | ✓ purchased | Mifare — confirm MFRC522 compatibility |

## Door Actuation
| Part | Qty | Est. Cost | Notes |
|---|---|---|---|
| RVMARINEPAT 12V Linear Actuator (4" stroke, 14mm/s, 220lbs) | 1 | ✓ purchased | Drives door open and closed — replaces solenoid + flap |
| WWZMDiB L298N Motor Driver Controller Board (2-pack) | 1 | ✓ purchased | Lets Pi control actuator direction via GPIO |

## Power
| Part | Qty | Est. Cost | Notes |
|---|---|---|---|
| Voltset 30W Solar Panel Kit | 1 | ✓ purchased | Includes 30W panel, 10A MPPT charge controller, and mount bracket — search B0C9PRGVKM on Amazon |
| ExpertPower 12V 7Ah SLA Battery | 1 | ✓ purchased | ~3–4 days backup with no sun — keep shaded. Not included in Voltset kit. Search B003S1RQ2S on Amazon. |
| DROK Waterproof DC Buck Converter (8-22V in, 3-15V out, 3A) | 1 | ✓ purchased | Set output to 5V to power the Pi. Search B00C0KL1OM on Amazon. |
| Wisesorb Silica Gel Packets (20g, 15-pack) | 1 lot | ~TBD | Prevent condensation inside enclosures — 1-2 packs per enclosure. Search B0BB6N6581 on Amazon. |

## Physical Door
| Part | Qty | Est. Cost | Notes |
|---|---|---|---|
| Aluminum flat bar for frame | 1 lot | ~$15 | Cut to size at hardware store |
| Aluminum or weatherproof plastic hinged panel | 1 | ~$10 | Driven by actuator — replaces rubber flap |
| Stainless hinges + screws | 1 lot | ~$10 | Anything exposed to weather must be stainless |
| Weatherproof override pushbutton | 1 | ~$8 | IP65+, panel-mount |

## Door Dimensions
- Target clear opening: **10" × 15"** (standard for 26–40 lb dogs)

## Power Notes
- Validate sun exposure on the fence section before finalising panel size
- South-facing is ideal; heavy shade may require a larger panel or remote panel mount
- Actuator draws 2–5A under load but only briefly during open/close cycles
- Keep battery enclosure shaded — SLA batteries degrade faster in high heat

## Enclosure Notes
- Pi enclosure (8.7"×6.7"×4.3") fits Pi, both RFID readers, buck converter, and wiring comfortably
- Battery and charge controller live in a separate weatherproof box
- Use light-colored enclosure for Pi to reflect solar heat
