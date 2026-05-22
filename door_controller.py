import RPi.GPIO as GPIO
from mfrc522 import MFRC522, SimpleMFRC522
import time
import os
import threading
import json
import urllib.request
import signal

# RFID tag IDs
AUTHORIZED_TAGS = {613025449752, 372068189196}

# Default home-side assignment — set each to the tag ID of the dog on that reader's side of the fence
READER1_HOME_TAG = 613025449752
READER2_HOME_TAG = 372068189196

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

# Firebase
FIREBASE_KEY = '/home/pat0222/dog-door/firebase-key.json'
FIREBASE_URL = 'https://dog-door-632e6-default-rtdb.firebaseio.com/'

_firebase_lock = threading.Lock()
_owner_available = [True, True]  # default True so door works if Firebase is unreachable
_firebase_command = None
_stop_requested = False
_firebase_db = None


def init_firebase():
    global _firebase_db
    try:
        import firebase_admin
        from firebase_admin import credentials, db
        cred = credentials.Certificate(FIREBASE_KEY)
        firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_URL})
        _firebase_db = db

        def make_owner_listener(idx):
            def on_owner(event):
                if isinstance(event.data, dict):
                    with _firebase_lock:
                        _owner_available[idx] = bool(event.data.get('available', True))
            return on_owner

        def on_command(event):
            global _firebase_command, _stop_requested
            if event.data:
                if event.data == 'stop':
                    with _firebase_lock:
                        _stop_requested = True
                    try:
                        db.reference('command').set(None)
                    except Exception:
                        pass
                else:
                    with _firebase_lock:
                        _firebase_command = event.data

        db.reference('owners/owner1').listen(make_owner_listener(0))
        db.reference('owners/owner2').listen(make_owner_listener(1))
        db.reference('command').listen(on_command)
        print("Firebase connected")
    except Exception as e:
        print(f"Firebase unavailable: {e} — operating locally")


def both_owners_available():
    with _firebase_lock:
        return _owner_available[0] and _owner_available[1]


def poll_firebase_command():
    global _firebase_command
    with _firebase_lock:
        cmd = _firebase_command
        _firebase_command = None
    if cmd and _firebase_db:
        try:
            _firebase_db.reference('command').set(None)
        except Exception:
            pass
    return cmd


def send_push_notification(title, body):
    def _send():
        if _firebase_db is None:
            return
        try:
            tokens = _firebase_db.reference('push_tokens').get()
            if not tokens:
                return
            token_list = list(tokens.values()) if isinstance(tokens, dict) else list(tokens)
            payload = [{'to': t, 'title': title, 'body': body, 'sound': 'default'}
                       for t in token_list if t]
            if not payload:
                return
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                'https://exp.host/--/api/v2/push/send',
                data=data,
                headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            print(f"Push notification error: {e}")
    threading.Thread(target=_send, daemon=True).start()


def push_progress(estimated_pos):
    if _firebase_db is None:
        return
    try:
        _firebase_db.reference('door').update({
            'open_pct': round((1.0 - estimated_pos) * 100)
        })
    except Exception:
        pass


def push_door_state():
    if _firebase_db is None:
        return
    try:
        _firebase_db.reference('door').set({
            'state': door_state,
            'open_pct': round((1.0 - actuator_pos) * 100)
        })
    except Exception:
        pass


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
    push_door_state()


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
    global actuator_pos, _stop_requested
    set_state(PARTIALLY_OPEN)
    retract()
    travel_secs = actuator_pos * ACTUATOR_TRAVEL_SECS
    start = time.monotonic()
    last_push = start
    while time.monotonic() - start < travel_secs:
        time.sleep(0.1)
        now = time.monotonic()
        if now - last_push >= 0.5:
            push_progress(max(0.0, actuator_pos - (now - start) / ACTUATOR_TRAVEL_SECS))
            last_push = now
        if _stop_requested:
            stop()
            elapsed = time.monotonic() - start
            actuator_pos = max(0.0, actuator_pos - elapsed / ACTUATOR_TRAVEL_SECS)
            set_state(OPEN if actuator_pos <= 0.0 else PARTIALLY_OPEN)
            _stop_requested = False
            print("Door open interrupted")
            return False
    stop()
    actuator_pos = 0.0
    set_state(OPEN)
    print("Door open")
    return True


def close_door(reader1, reader2, home_tag=None):
    global closing, actuator_pos, _stop_requested
    closing = True
    set_state(PARTIALLY_CLOSED)
    print("Closing in progress...")
    extend()
    travel_secs = (1.0 - actuator_pos) * ACTUATOR_TRAVEL_SECS
    start = time.monotonic()
    last_push = start
    while time.monotonic() - start < travel_secs:
        time.sleep(0.1)
        now = time.monotonic()
        if now - last_push >= 0.5:
            push_progress(min(1.0, actuator_pos + (now - start) / ACTUATOR_TRAVEL_SECS))
            last_push = now
        if _stop_requested:
            stop()
            elapsed = time.monotonic() - start
            actuator_pos = min(1.0, actuator_pos + elapsed / ACTUATOR_TRAVEL_SECS)
            set_state(CLOSED if actuator_pos >= 1.0 else PARTIALLY_CLOSED)
            closing = False
            _stop_requested = False
            print("Door close interrupted")
            return False
        per_reader = scan_tags_per_reader(reader1, reader2)
        if home_tag and home_tag[0] is not None:
            reverse = (
                (per_reader[0] is not None and per_reader[0] != home_tag[0]) or
                (per_reader[1] is not None and per_reader[1] != home_tag[1])
            )
        else:
            reverse = any(t is not None for t in per_reader)
        if reverse:
            print("Tag on wrong side during close — reversing")
            stop()
            actuator_pos = min(1.0, actuator_pos + (time.monotonic() - start) / ACTUATOR_TRAVEL_SECS)
            time.sleep(0.2)
            open_door()
            closing = False
            return False
    stop()
    actuator_pos = 1.0
    closing = False
    set_state(CLOSED)
    print("Door closed")
    return True


def open_door_manual():
    global closing, actuator_pos
    closing = True
    set_state(PARTIALLY_OPEN)
    print("Manual open in progress...")
    retract()
    travel_secs = actuator_pos * ACTUATOR_TRAVEL_SECS
    start = time.monotonic()
    last_push = start
    while time.monotonic() - start < travel_secs:
        time.sleep(0.1)
        now = time.monotonic()
        if now - last_push >= 0.5:
            push_progress(max(0.0, actuator_pos - (now - start) / ACTUATOR_TRAVEL_SECS))
            last_push = now
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
            return False
    stop()
    actuator_pos = 0.0
    set_state(OPEN)
    closing = False
    print("Door open (manual)")
    return True


def close_door_manual():
    global closing, actuator_pos
    closing = True
    set_state(PARTIALLY_CLOSED)
    print("Manual close in progress...")
    extend()
    travel_secs = (1.0 - actuator_pos) * ACTUATOR_TRAVEL_SECS
    start = time.monotonic()
    last_push = start
    while time.monotonic() - start < travel_secs:
        time.sleep(0.1)
        now = time.monotonic()
        if now - last_push >= 0.5:
            push_progress(min(1.0, actuator_pos + (now - start) / ACTUATOR_TRAVEL_SECS))
            last_push = now
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
            return False
    stop()
    actuator_pos = 1.0
    set_state(CLOSED)
    closing = False
    print("Door closed (manual)")
    return True


def scan_tags_per_reader(reader1, reader2):
    result = []
    for reader in [reader1, reader2]:
        tag = None
        (status, _) = reader.READER.MFRC522_Request(reader.READER.PICC_REQALL)
        if status == reader.READER.MI_OK:
            (status, uid) = reader.READER.MFRC522_Anticoll()
            if status == reader.READER.MI_OK:
                t = 0
                for byte in uid:
                    t = t * 256 + byte
                if t in AUTHORIZED_TAGS:
                    tag = t
        reader.READER.MFRC522_Init()
        result.append(tag)
    return result  # [tag_at_reader1|None, tag_at_reader2|None]


def scan_tags(reader1, reader2):
    return {t for t in scan_tags_per_reader(reader1, reader2) if t is not None}


def main():
    global closing

    setup_gpio()
    init_firebase()

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
    home_tag = [None, None]        # tag that belongs on each reader's side, set when door opens via RFID
    last_seen = [None, None]       # most recent authorized tag detected by each reader
    home_detected_time = [None, None]  # when each reader last saw its home dog
    close_deadline = None

    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))

    try:
        while True:
            sw_open  = GPIO.input(SW_OPEN)
            sw_close = GPIO.input(SW_CLOSE)

            # Manual switch takes priority — act only on rising edge
            if sw_open and not prev_sw_open and door_state != OPEN and not closing:
                print("Manual switch — opening door")
                if open_door_manual():
                    send_push_notification("Puppy Play Time", "Door opened manually.")
                home_tag[:] = [READER1_HOME_TAG, READER2_HOME_TAG]
                last_seen[:] = [None, None]
                home_detected_time[:] = [None, None]
                close_deadline = None
            elif sw_close and not prev_sw_close and door_state != CLOSED and not closing:
                print("Manual switch — closing door")
                if close_door_manual():
                    send_push_notification("Puppy Play Time", "Door closed manually.")
                home_tag[:] = [READER1_HOME_TAG, READER2_HOME_TAG]
                last_seen[:] = [None, None]
                home_detected_time[:] = [None, None]
                close_deadline = None

            prev_sw_open  = sw_open
            prev_sw_close = sw_close

            if not closing:
                # Handle app commands
                cmd = poll_firebase_command()
                if cmd == 'open' and door_state != OPEN and both_owners_available():
                    print("App command — opening door")
                    if open_door():
                        send_push_notification("Puppy Play Time", "Door opened via app.")
                    home_tag[:] = [READER1_HOME_TAG, READER2_HOME_TAG]
                    last_seen[:] = [None, None]
                    home_detected_time[:] = [None, None]
                    close_deadline = None
                elif cmd == 'close' and door_state != CLOSED:
                    print("App command — closing door")
                    if close_door(reader1, reader2):
                        send_push_notification("Puppy Play Time", "Door closed via app.")
                    home_tag[:] = [READER1_HOME_TAG, READER2_HOME_TAG]
                    last_seen[:] = [None, None]
                    home_detected_time[:] = [None, None]
                    close_deadline = None

                per_reader = scan_tags_per_reader(reader1, reader2)
                tags = {t for t in per_reader if t is not None}

                if is_closed():
                    if (per_reader[0] is not None and per_reader[1] is not None
                            and per_reader[0] != per_reader[1]
                            and both_owners_available()):
                        print("Both tags on opposite sides — opening door")
                        home_tag[:] = per_reader
                        last_seen[:] = [None, None]
                        home_detected_time[:] = [None, None]
                        close_deadline = None
                        if open_door():
                            send_push_notification("Puppy Play Time", "Door opened — the dogs are playing.")

                elif is_open():
                    for i, tag in enumerate(per_reader):
                        if tag is not None:
                            last_seen[i] = tag
                            if home_tag[i] is not None and tag == home_tag[i]:
                                home_detected_time[i] = time.time()

                    cross_detected = home_tag[0] is not None and (
                        (per_reader[0] is not None and per_reader[0] != home_tag[0]) or
                        (per_reader[1] is not None and per_reader[1] != home_tag[1])
                    )
                    either_home = (home_tag[0] is not None
                                   and any(t is not None for t in home_detected_time))

                    if either_home and not cross_detected:
                        if close_deadline is None:
                            print(f"Dog home detected — closing in {CLOSE_DELAY_SECS}s")
                            close_deadline = time.time() + CLOSE_DELAY_SECS
                        elif time.time() >= close_deadline:
                            close_deadline = None
                            if close_door(reader1, reader2, home_tag):
                                send_push_notification("Puppy Play Time", "Dogs are home. Door closed.")
                    else:
                        if close_deadline is not None:
                            print("Dog activity detected — cancelling close")
                        close_deadline = None
                        if cross_detected:
                            home_detected_time[:] = [None, None]

                now = time.time()
                if now - last_status >= STATUS_INTERVAL:
                    r1_str = str(per_reader[0]) if per_reader[0] is not None else 'none'
                    r2_str = str(per_reader[1]) if per_reader[1] is not None else 'none'
                    sw_str = 'open' if sw_open else ('close' if sw_close else 'neutral')
                    open_pct = round((1.0 - actuator_pos) * 100)
                    avail_str = 'both' if both_owners_available() else ('owner1' if _owner_available[0] else ('owner2' if _owner_available[1] else 'none'))
                    print(f"[status] door={door_state} ({open_pct}%) | r1={r1_str} | r2={r2_str} | switch={sw_str} | owners={avail_str}")
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
