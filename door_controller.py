import RPi.GPIO as GPIO
from mfrc522 import MFRC522, SimpleMFRC522
import time
import os

# RFID tag IDs
AUTHORIZED_TAGS = {613025449752, 372068189196}

# GPIO pins (BCM)
IN1 = 17
IN2 = 27
ENA = 22
SW_OPEN  = 5    # GPIO5 (Pin 29) — manual switch +VE(Load) — retracts actuator, opens door
SW_CLOSE = 6    # GPIO6 (Pin 31) — manual switch -VE(Load) — extends actuator, closes door

# Timing
CLOSE_DELAY_SECS = 10
ACTUATOR_TRAVEL_SECS = 7.84
STATUS_INTERVAL = 2

# Door states
OPEN            = 'open'
CLOSED          = 'closed'
PARTIALLY_OPEN  = 'partially_open'
PARTIALLY_CLOSED = 'partially_closed'

VALID_STATES = {OPEN, CLOSED, PARTIALLY_OPEN, PARTIALLY_CLOSED}

# State
STATE_FILE = '/home/pat0222/dog-door/.door_state'
closing = False
actuator_pos = 1.0  # 0.0 = fully retracted (open), 1.0 = fully extended (closed)


def load_door_state():
    global actuator_pos
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            parts = f.read().strip().split()
        state = parts[0] if parts else None
        if state in VALID_STATES:
            if state == OPEN:
                actuator_pos = 0.0
            elif state == CLOSED:
                actuator_pos = 1.0
            elif len(parts) == 2:
                try:
                    actuator_pos = float(parts[1])
                except ValueError:
                    actuator_pos = 0.5
            else:
                actuator_pos = 0.5
            return state
    actuator_pos = 1.0
    return CLOSED


def save_door_state(state):
    with open(STATE_FILE, 'w') as f:
        if state in (PARTIALLY_OPEN, PARTIALLY_CLOSED):
            f.write(f"{state} {actuator_pos:.3f}")
        else:
            f.write(state)


def set_state(state):
    global door_state
    door_state = state
    save_door_state(state)


def is_open():
    return door_state in (OPEN, PARTIALLY_OPEN)


def is_closed():
    return door_state in (CLOSED, PARTIALLY_CLOSED)


door_state = load_door_state()


def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(IN1, GPIO.OUT)
    GPIO.setup(IN2, GPIO.OUT)
    GPIO.setup(ENA, GPIO.OUT)
    GPIO.setup(SW_OPEN,  GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    GPIO.setup(SW_CLOSE, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    stop()


def extend():
    print("Extending actuator...")
    GPIO.output(IN1, GPIO.HIGH)
    GPIO.output(IN2, GPIO.LOW)
    GPIO.output(ENA, GPIO.HIGH)


def retract():
    print("Retracting actuator...")
    GPIO.output(IN1, GPIO.LOW)
    GPIO.output(IN2, GPIO.HIGH)
    GPIO.output(ENA, GPIO.HIGH)


def stop():
    GPIO.output(ENA, GPIO.LOW)


def open_door():
    global actuator_pos
    retract()
    time.sleep(actuator_pos * ACTUATOR_TRAVEL_SECS)
    stop()
    actuator_pos = 0.0
    set_state(OPEN)
    print("Door open")


def close_door(reader1, reader2):
    global closing, actuator_pos
    closing = True
    set_state(CLOSED)
    print("Closing in progress...")
    extend()
    travel_secs = (1.0 - actuator_pos) * ACTUATOR_TRAVEL_SECS
    start = time.monotonic()
    while time.monotonic() - start < travel_secs:
        time.sleep(0.1)
        tags = scan_tags(reader1, reader2)
        if tags:
            print("Tag detected during close — reversing")
            stop()
            actuator_pos = min(1.0, actuator_pos + (time.monotonic() - start) / ACTUATOR_TRAVEL_SECS)
            time.sleep(0.2)
            open_door()
            closing = False
            return
    stop()
    actuator_pos = 1.0
    closing = False
    print("Door closed")


def open_door_manual():
    global closing, actuator_pos
    closing = True
    print("Manual open in progress...")
    retract()
    travel_secs = actuator_pos * ACTUATOR_TRAVEL_SECS
    start = time.monotonic()
    while time.monotonic() - start < travel_secs:
        time.sleep(0.1)
        if not GPIO.input(SW_OPEN):
            stop()
            actuator_pos = max(0.0, actuator_pos - (time.monotonic() - start) / ACTUATOR_TRAVEL_SECS)
            if GPIO.input(SW_CLOSE):
                print("Manual switch reversed — closing")
                time.sleep(0.1)
                close_door_manual()
            else:
                print("Manual open stopped")
                set_state(PARTIALLY_OPEN)
                closing = False
            return
    stop()
    actuator_pos = 0.0
    set_state(OPEN)
    closing = False
    print("Door open (manual)")


def close_door_manual():
    global closing, actuator_pos
    closing = True
    print("Manual close in progress...")
    extend()
    travel_secs = (1.0 - actuator_pos) * ACTUATOR_TRAVEL_SECS
    start = time.monotonic()
    while time.monotonic() - start < travel_secs:
        time.sleep(0.1)
        if not GPIO.input(SW_CLOSE):
            stop()
            actuator_pos = min(1.0, actuator_pos + (time.monotonic() - start) / ACTUATOR_TRAVEL_SECS)
            if GPIO.input(SW_OPEN):
                print("Manual switch reversed — opening")
                time.sleep(0.1)
                open_door_manual()
            else:
                print("Manual close stopped")
                set_state(PARTIALLY_CLOSED)
                closing = False
            return
    stop()
    actuator_pos = 1.0
    set_state(CLOSED)
    closing = False
    print("Door closed (manual)")


def scan_tags(reader1, reader2):
    detected = set()
    for reader in [reader1, reader2]:
        (status, _) = reader.READER.MFRC522_Request(reader.READER.PICC_REQALL)
        if status == reader.READER.MI_OK:
            (status, uid) = reader.READER.MFRC522_Anticoll()
            if status == reader.READER.MI_OK:
                tag = 0
                for byte in uid:
                    tag = tag * 256 + byte
                if tag in AUTHORIZED_TAGS:
                    detected.add(tag)
        reader.READER.MFRC522_Init()
    return detected


def main():
    global closing

    setup_gpio()

    rfid1 = MFRC522(bus=0, device=0, pin_rst=25)
    rfid2 = MFRC522(bus=0, device=1, pin_rst=24)

    reader1 = SimpleMFRC522()
    reader1.READER = rfid1

    reader2 = SimpleMFRC522()
    reader2.READER = rfid2

    print(f"Dog door ready — state: {door_state}")

    prev_sw_open  = False
    prev_sw_close = False
    last_status = 0

    try:
        while True:
            sw_open  = GPIO.input(SW_OPEN)
            sw_close = GPIO.input(SW_CLOSE)

            # Manual switch takes priority — act only on rising edge
            if sw_open and not prev_sw_open and door_state != OPEN and not closing:
                print("Manual switch — opening door")
                open_door_manual()
            elif sw_close and not prev_sw_close and door_state != CLOSED and not closing:
                print("Manual switch — closing door")
                close_door_manual()

            prev_sw_open  = sw_open
            prev_sw_close = sw_close

            if not closing:
                tags = scan_tags(reader1, reader2)

                if is_closed():
                    if len(tags) == 2:
                        print("Both tags detected — opening door")
                        open_door()

                elif is_open():
                    if len(tags) == 1:
                        print(f"One tag detected — closing in {CLOSE_DELAY_SECS}s")
                        deadline = time.time() + CLOSE_DELAY_SECS
                        cancelled = False
                        while time.time() < deadline:
                            time.sleep(0.5)
                            tags = scan_tags(reader1, reader2)
                            if len(tags) == 2:
                                print("Second tag returned — cancelling close")
                                cancelled = True
                                break
                        if not cancelled:
                            close_door(reader1, reader2)

                now = time.time()
                if now - last_status >= STATUS_INTERVAL:
                    tag_str = ', '.join(str(t) for t in tags) if tags else 'none'
                    sw_str = 'open' if sw_open else ('close' if sw_close else 'neutral')
                    open_pct = round((1.0 - actuator_pos) * 100)
                    print(f"[status] door={door_state} ({open_pct}%) | tags={tag_str} | switch={sw_str}")
                    last_status = now

            time.sleep(0.2)

    except KeyboardInterrupt:
        print("Shutting down")
    finally:
        stop()
        try:
            rfid1.spi.close()
            rfid2.spi.close()
        except Exception:
            pass
        GPIO.cleanup()


if __name__ == '__main__':
    main()
