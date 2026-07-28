import RPi.GPIO as GPIO
# from mfrc522 import MFRC522, SimpleMFRC522  # UHF RFID upgrade pending — see README
import time
import os
import threading
import json
import urllib.request
import signal
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from astral import LocationInfo
from astral.sun import sun as astral_sun

# --- RFID tag IDs (reserved for UHF RFID upgrade) ---
# AUTHORIZED_TAGS  = {613025449752, 372068189196}
# READER1_HOME_TAG = 613025449752
# READER2_HOME_TAG = 372068189196

# GPIO pins (BCM)
IN1      = 17
IN2      = 27
ENA      = 22
SW_OPEN  = 6    # GPIO6 (Pin 31) — manual switch, direction reversed in software
SW_CLOSE = 5    # GPIO5 (Pin 29) — manual switch, direction reversed in software

# LED pins (BCM) — driven via 2N2222 NPN transistors from 12V
LED_OPEN      = 20  # GPIO20 (Pin 38) — blue
LED_CLOSED    = 16  # GPIO16 (Pin 36) — red
LED_COUNTDOWN = 12  # GPIO12 (Pin 32) — amber
LED_OWNER1    = 13  # GPIO13 (Pin 33) — green
LED_OWNER2    = 26  # GPIO26 (Pin 37) — white (Ginger)

# Physical LED color → GPIO pin (fixed; used by test mode regardless of LED_* assignments)
_TEST_LED_PINS = {'green': 20, 'yellow': 12, 'red': 16, 'blue': 13, 'white': 26}

# Timing
CLOSE_DELAY_SECS     = 10
ACTUATOR_OPEN_SECS      = 5.59  # time to fully retract (open) — tune after install
ACTUATOR_CLOSE_SECS     = 5.84  # time to fully extend (close) — tune after install
ACTUATOR_OVERSHOOT_SECS = 0.5   # extra run after timer to guarantee endpoint is reached
STATUS_INTERVAL      = 2
STUCK_ALERT_SECS     = 900   # 15 minutes in a partial state triggers flashing LEDs

# Door states
OPEN             = 'open'
CLOSED           = 'closed'
PARTIALLY_OPEN   = 'partially_open'
PARTIALLY_CLOSED = 'partially_closed'

VALID_STATES = {OPEN, CLOSED, PARTIALLY_OPEN, PARTIALLY_CLOSED}

# Firebase
FIREBASE_KEY = '/home/pat0222/dog-door/firebase-key.json'
FIREBASE_URL = 'https://dog-door-632e6-default-rtdb.firebaseio.com/'

_firebase_lock   = threading.RLock()
_owner_available = [True, True]  # default True so door works if Firebase is unreachable
_firebase_command = None
_stop_requested  = False
_actuator_open_secs  = ACTUATOR_OPEN_SECS
_actuator_close_secs = ACTUATOR_CLOSE_SECS
_notifications = {'door': False}
_firebase_db     = None
_firebase_connected = False
_startup_time    = time.monotonic()

NIGHT_OFF_START  = 22   # hour when LEDs turn off
NIGHT_OFF_END    = 7    # hour when LEDs turn back on
DIM_DUTY_CYCLE   = 10   # percent during dawn/dusk
TRANSITION_MINS  = 60   # minutes of gradual fade around sunrise/sunset

TIMEZONE = ZoneInfo("America/New_York")
LOCATION = LocationInfo("South Riding", "USA", "America/New_York", 38.9318, -77.5103)

_night_mode_override = None   # None=auto, True=force dim, False=force bright
_night_off_override  = False  # True=bypass the 10PM–7AM off window
_led_pwm = {}
_sun_cache = {'date': None, 'sunrise': None, 'sunset': None}

_test_mode        = False
_test_leds        = {'green': False, 'yellow': False, 'red': False, 'blue': False, 'white': False}
_test_switch_cmd  = None
_test_sw_reported = {'open': None, 'close': None}

# IPC files
STATE_FILE = '/home/pat0222/dog-door/.door_state'
BEEP_FILE  = '/home/pat0222/dog-door/.beep_request'


def _get_sun_times():
    today = datetime.now(tz=TIMEZONE).date()
    if _sun_cache['date'] != today:
        s = astral_sun(LOCATION.observer, date=today, tzinfo=TIMEZONE)
        _sun_cache['date']    = today
        _sun_cache['sunrise'] = s['sunrise']
        _sun_cache['sunset']  = s['sunset']
    return _sun_cache['sunrise'], _sun_cache['sunset']


def get_led_duty_cycle():
    with _firebase_lock:
        night_off_bypass    = _night_off_override
        brightness_override = _night_mode_override

    now = datetime.now(tz=TIMEZONE)

    # 10 PM – 7 AM: LEDs off unless bypassed
    if (now.hour >= NIGHT_OFF_START or now.hour < NIGHT_OFF_END) and not night_off_bypass:
        return 0

    # Manual brightness override from app (Night Mode segmented control)
    if brightness_override is True:
        return DIM_DUTY_CYCLE
    if brightness_override is False:
        return 100

    # Auto: smooth fade around sunrise/sunset
    sunrise, sunset = _get_sun_times()
    half = timedelta(minutes=TRANSITION_MINS // 2)

    if sunrise - half <= now <= sunrise + half:
        t = (now - (sunrise - half)).total_seconds() / (TRANSITION_MINS * 60)
        return int(DIM_DUTY_CYCLE + (100 - DIM_DUTY_CYCLE) * max(0.0, min(1.0, t)))

    if sunset - half <= now <= sunset + half:
        t = (now - (sunset - half)).total_seconds() / (TRANSITION_MINS * 60)
        return int(100 - (100 - DIM_DUTY_CYCLE) * max(0.0, min(1.0, t)))

    if sunrise + half < now < sunset - half:
        return 100  # full daytime

    return DIM_DUTY_CYCLE  # dawn/dusk outside transition window


def led_on(pin):
    _led_pwm[pin].ChangeDutyCycle(get_led_duty_cycle())


def led_off(pin):
    _led_pwm[pin].ChangeDutyCycle(0)


def write_beep_request(name):
    try:
        tmp = BEEP_FILE + '.tmp'
        with open(tmp, 'w') as f:
            f.write(name)
        os.replace(tmp, BEEP_FILE)
    except Exception:
        pass


def init_firebase():
    global _firebase_db, _firebase_connected
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
                        db.reference('command').delete()
                    except Exception:
                        pass
                else:
                    with _firebase_lock:
                        _firebase_command = event.data

        def on_test_active(event):
            global _test_mode
            with _firebase_lock:
                prev = _test_mode
                _test_mode = bool(event.data) if event.data is not None else False
                if _test_mode != prev:
                    print(f"[TEST] Test mode {'activated' if _test_mode else 'deactivated'}")

        def on_test_leds(event):
            leds = event.data or {}
            with _firebase_lock:
                for color in _test_leds:
                    _test_leds[color] = bool(leds.get(color, False))

        def on_test_switch(event):
            global _test_switch_cmd
            if event.data:
                with _firebase_lock:
                    if not _test_switch_cmd:
                        _test_switch_cmd = event.data

        def on_night_mode(event):
            global _night_mode_override
            with _firebase_lock:
                data = event.data
                _night_mode_override = None if data is None else bool(data)

        def on_night_off_override(event):
            global _night_off_override
            with _firebase_lock:
                _night_off_override = bool(event.data) if event.data is not None else False

        def on_actuator_open_secs(event):
            global _actuator_open_secs
            if event.data is not None:
                try:
                    val = float(event.data)
                    if 1.0 <= val <= 30.0:
                        with _firebase_lock:
                            _actuator_open_secs = val
                        print(f"Actuator open secs: {val}")
                except (ValueError, TypeError):
                    pass

        def on_actuator_close_secs(event):
            global _actuator_close_secs
            if event.data is not None:
                try:
                    val = float(event.data)
                    if 1.0 <= val <= 30.0:
                        with _firebase_lock:
                            _actuator_close_secs = val
                        print(f"Actuator close secs: {val}")
                except (ValueError, TypeError):
                    pass

        db.reference('owners/owner1').listen(make_owner_listener(0))
        db.reference('owners/owner2').listen(make_owner_listener(1))
        db.reference('command').listen(on_command)
        db.reference('test/active').listen(on_test_active)
        db.reference('test/leds').listen(on_test_leds)
        db.reference('test/switch').listen(on_test_switch)
        db.reference('settings/night_mode_override').listen(on_night_mode)
        db.reference('settings/night_off_override').listen(on_night_off_override)
        def on_notifications(event):
            with _firebase_lock:
                data = event.data if isinstance(event.data, dict) else {}
                _notifications['door'] = bool(data.get('door', False))

        db.reference('settings/actuator_open_secs').listen(on_actuator_open_secs)
        db.reference('settings/actuator_close_secs').listen(on_actuator_close_secs)
        db.reference('settings/notifications').listen(on_notifications)
        _firebase_connected = True
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
            _firebase_db.reference('command').delete()
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
    global _firebase_connected
    if _firebase_db is None:
        return
    try:
        _firebase_db.reference('door').update({
            'open_pct': max(0, min(100, round((1.0 - estimated_pos) * 100)))
        })
        _firebase_connected = True
    except Exception:
        _firebase_connected = False


def push_door_state():
    global _firebase_connected
    if _firebase_db is None:
        return
    try:
        _firebase_db.reference('door').set({
            'state': door_state,
            'open_pct': max(0, min(100, round((1.0 - actuator_pos) * 100)))
        })
        _firebase_connected = True
    except Exception:
        _firebase_connected = False


closing    = False
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
    try:
        with open(STATE_FILE, 'w') as f:
            if state in (PARTIALLY_OPEN, PARTIALLY_CLOSED):
                f.write(f"{state} {actuator_pos:.3f}")
            else:
                f.write(state)
    except OSError as e:
        print(f"Failed to save door state: {e}")


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
    GPIO.setup(IN1,      GPIO.OUT)
    GPIO.setup(IN2,      GPIO.OUT)
    GPIO.setup(ENA,      GPIO.OUT)
    GPIO.setup(SW_OPEN,  GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    GPIO.setup(SW_CLOSE, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    GPIO.setup(LED_OPEN,      GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(LED_CLOSED,    GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(LED_COUNTDOWN, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(LED_OWNER1,    GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(LED_OWNER2,    GPIO.OUT, initial=GPIO.LOW)
    for pin in (LED_OPEN, LED_CLOSED, LED_COUNTDOWN, LED_OWNER1, LED_OWNER2):
        pwm = GPIO.PWM(pin, 200)
        pwm.start(0)
        _led_pwm[pin] = pwm
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


_LED_SEQUENCE = [LED_OPEN, LED_COUNTDOWN, LED_CLOSED, LED_OWNER1, LED_OWNER2]

def update_leds(countdown_active, stuck_alert):
    with _firebase_lock:
        if _test_mode:
            for color, pin in _TEST_LED_PINS.items():
                led_on(pin) if _test_leds[color] else led_off(pin)
            return

    in_grace = time.monotonic() - _startup_time < 5
    if not _firebase_connected and not in_grace:
        slot = int(time.monotonic() / 0.3) % len(_LED_SEQUENCE)
        for i, pin in enumerate(_LED_SEQUENCE):
            led_on(pin) if i == slot else led_off(pin)
        return

    blink = int(time.monotonic() * 2) % 2 == 0
    if stuck_alert:
        for pin in (LED_OPEN, LED_CLOSED, LED_COUNTDOWN):
            led_on(pin) if blink else led_off(pin)
    else:
        if door_state == PARTIALLY_OPEN:
            led_on(LED_OPEN) if blink else led_off(LED_OPEN)
        else:
            led_on(LED_OPEN) if is_open() else led_off(LED_OPEN)
        if door_state == PARTIALLY_CLOSED:
            led_on(LED_CLOSED) if blink else led_off(LED_CLOSED)
        else:
            led_on(LED_CLOSED) if is_closed() else led_off(LED_CLOSED)
        led_on(LED_COUNTDOWN) if countdown_active else led_off(LED_COUNTDOWN)

    with _firebase_lock:
        led_on(LED_OWNER1) if _owner_available[0] else led_off(LED_OWNER1)
        led_on(LED_OWNER2) if _owner_available[1] else led_off(LED_OWNER2)


def open_door():
    global actuator_pos, _stop_requested
    with _firebase_lock:
        open_secs = _actuator_open_secs
    set_state(PARTIALLY_OPEN)
    retract()
    travel_secs = actuator_pos * open_secs
    start = time.monotonic()
    last_push = start
    while time.monotonic() - start < travel_secs:
        time.sleep(0.1)
        now = time.monotonic()
        update_leds(False, False)
        if now - last_push >= 0.5:
            push_progress(max(0.0, actuator_pos - (now - start) / open_secs))
            last_push = now
        if _stop_requested:
            stop()
            elapsed = time.monotonic() - start
            actuator_pos = max(0.0, actuator_pos - elapsed / open_secs)
            set_state(OPEN if actuator_pos <= 0.0 else PARTIALLY_OPEN)
            _stop_requested = False
            print("Door open interrupted")
            return False
    overshoot_end = time.monotonic() + ACTUATOR_OVERSHOOT_SECS
    while time.monotonic() < overshoot_end:
        time.sleep(0.05)
        if _stop_requested:
            break
    stop()
    actuator_pos = 0.0
    set_state(OPEN)
    print("Door open")
    return True


def close_door():
    global closing, actuator_pos, _stop_requested
    with _firebase_lock:
        close_secs = _actuator_close_secs
    closing = True
    set_state(PARTIALLY_CLOSED)
    print("Closing in progress...")
    extend()
    travel_secs = (1.0 - actuator_pos) * close_secs
    start = time.monotonic()
    last_push = start
    while time.monotonic() - start < travel_secs:
        time.sleep(0.1)
        now = time.monotonic()
        update_leds(False, False)
        if now - last_push >= 0.5:
            push_progress(min(1.0, actuator_pos + (now - start) / close_secs))
            last_push = now
        if _stop_requested:
            stop()
            elapsed = time.monotonic() - start
            actuator_pos = min(1.0, actuator_pos + elapsed / close_secs)
            set_state(CLOSED if actuator_pos >= 1.0 else PARTIALLY_CLOSED)
            closing = False
            _stop_requested = False
            print("Door close interrupted")
            return False
        # --- RFID reverse-on-tag logic (reserved for UHF RFID upgrade) ---
    overshoot_end = time.monotonic() + ACTUATOR_OVERSHOOT_SECS
    while time.monotonic() < overshoot_end:
        time.sleep(0.05)
        if _stop_requested:
            break
    stop()
    actuator_pos = 1.0
    closing = False
    set_state(CLOSED)
    print("Door closed")
    return True


def open_door_manual():
    global closing, actuator_pos
    with _firebase_lock:
        open_secs = _actuator_open_secs
    closing = True
    set_state(PARTIALLY_OPEN)
    print("Manual open in progress...")
    retract()
    travel_secs = actuator_pos * open_secs
    start = time.monotonic()
    last_push = start
    while time.monotonic() - start < travel_secs:
        time.sleep(0.1)
        now = time.monotonic()
        update_leds(False, False)
        if now - last_push >= 0.5:
            push_progress(max(0.0, actuator_pos - (now - start) / open_secs))
            last_push = now
        if not GPIO.input(SW_OPEN):
            stop()
            actuator_pos = max(0.0, actuator_pos - (time.monotonic() - start) / open_secs)
            if GPIO.input(SW_CLOSE):
                print("Manual switch reversed — closing")
                time.sleep(0.1)
                close_door_manual()
            else:
                print("Manual open stopped")
                set_state(PARTIALLY_OPEN)
                closing = False
            return False
    overshoot_end = time.monotonic() + ACTUATOR_OVERSHOOT_SECS
    while time.monotonic() < overshoot_end:
        time.sleep(0.05)
        if not GPIO.input(SW_OPEN):
            break
    stop()
    actuator_pos = 0.0
    set_state(OPEN)
    closing = False
    print("Door open (manual)")
    return True


def close_door_manual():
    global closing, actuator_pos
    with _firebase_lock:
        close_secs = _actuator_close_secs
    closing = True
    set_state(PARTIALLY_CLOSED)
    print("Manual close in progress...")
    extend()
    travel_secs = (1.0 - actuator_pos) * close_secs
    start = time.monotonic()
    last_push = start
    while time.monotonic() - start < travel_secs:
        time.sleep(0.1)
        now = time.monotonic()
        update_leds(False, False)
        if now - last_push >= 0.5:
            push_progress(min(1.0, actuator_pos + (now - start) / close_secs))
            last_push = now
        if not GPIO.input(SW_CLOSE):
            stop()
            actuator_pos = min(1.0, actuator_pos + (time.monotonic() - start) / close_secs)
            if GPIO.input(SW_OPEN):
                print("Manual switch reversed — opening")
                time.sleep(0.1)
                open_door_manual()
            else:
                print("Manual close stopped")
                set_state(PARTIALLY_CLOSED)
                closing = False
            return False
    overshoot_end = time.monotonic() + ACTUATOR_OVERSHOOT_SECS
    while time.monotonic() < overshoot_end:
        time.sleep(0.05)
        if not GPIO.input(SW_CLOSE):
            break
    stop()
    actuator_pos = 1.0
    set_state(CLOSED)
    closing = False
    print("Door closed (manual)")
    return True


# --- RFID scan functions (reserved for UHF RFID upgrade) ---


def main():
    global closing, _test_switch_cmd

    setup_gpio()
    init_firebase()

    print(f"Dog door ready — state: {door_state}")

    prev_sw_open    = False
    prev_sw_close   = False
    last_status     = 0
    last_stuck_beep = 0
    partial_since   = time.monotonic() if door_state in (PARTIALLY_OPEN, PARTIALLY_CLOSED) else None

    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))

    try:
        while True:
            sw_open  = GPIO.input(SW_OPEN)
            sw_close = GPIO.input(SW_CLOSE)

            with _firebase_lock:
                test_mode_active = _test_mode

            if test_mode_active:
                sw_open_bool  = bool(sw_open)
                sw_close_bool = bool(sw_close)
                if (sw_open_bool != _test_sw_reported['open'] or
                        sw_close_bool != _test_sw_reported['close']):
                    _test_sw_reported['open']  = sw_open_bool
                    _test_sw_reported['close'] = sw_close_bool
                    if sw_open_bool:
                        print("[TEST] Switch signal: open")
                    if sw_close_bool:
                        print("[TEST] Switch signal: close")
                    if _firebase_db:
                        try:
                            _firebase_db.reference('test/switch_state').set(
                                {'open': sw_open_bool, 'close': sw_close_bool}
                            )
                        except Exception:
                            pass
            else:
                if sw_open and not prev_sw_open and door_state != OPEN and not closing:
                    print("Manual switch — opening door")
                    if open_door_manual():
                        write_beep_request('open')
                        with _firebase_lock:
                            if _notifications['door']:
                                send_push_notification("Tail Gate RG", "Door opened manually.")
                elif sw_close and not prev_sw_close and door_state != CLOSED and not closing:
                    print("Manual switch — closing door")
                    if close_door_manual():
                        write_beep_request('close')
                        with _firebase_lock:
                            if _notifications['door']:
                                send_push_notification("Tail Gate RG", "Door closed manually.")

            prev_sw_open  = sw_open
            prev_sw_close = sw_close

            if not closing:
                with _firebase_lock:
                    test_sw = _test_switch_cmd
                    _test_switch_cmd = None
                if test_sw:
                    if test_sw == 'open' and door_state != OPEN:
                        print("[TEST] Switch: open")
                        if open_door():
                            write_beep_request('open')
                    elif test_sw == 'close' and door_state != CLOSED:
                        print("[TEST] Switch: close")
                        if close_door():
                            write_beep_request('close')
                    if _firebase_db:
                        try:
                            _firebase_db.reference('test/switch').delete()
                        except Exception:
                            pass

                cmd = poll_firebase_command()
                if cmd == 'open' and door_state != OPEN and both_owners_available():
                    print("App command — opening door")
                    if open_door():
                        write_beep_request('open')
                        with _firebase_lock:
                            if _notifications['door']:
                                send_push_notification("Tail Gate RG", "Door opened via app.")
                elif cmd == 'close' and door_state != CLOSED:
                    print("App command — closing door")
                    if close_door():
                        write_beep_request('close')
                        with _firebase_lock:
                            if _notifications['door']:
                                send_push_notification("Tail Gate RG", "Door closed via app.")

                # --- RFID open/close triggers (reserved for UHF RFID upgrade) ---

                if door_state in (PARTIALLY_OPEN, PARTIALLY_CLOSED):
                    if partial_since is None:
                        partial_since = time.monotonic()
                else:
                    partial_since = None
                stuck_alert = (partial_since is not None
                               and time.monotonic() - partial_since >= STUCK_ALERT_SECS)
                if stuck_alert and time.monotonic() - last_stuck_beep >= 30:
                    write_beep_request('stuck')
                    last_stuck_beep = time.monotonic()
                update_leds(False, stuck_alert)

                now = time.monotonic()
                if now - last_status >= STATUS_INTERVAL:
                    sw_str   = 'open' if sw_open else ('close' if sw_close else 'neutral')
                    open_pct = round((1.0 - actuator_pos) * 100)
                    with _firebase_lock:
                        o1, o2 = _owner_available[0], _owner_available[1]
                    avail_str = 'both' if (o1 and o2) else ('Rita' if o1 else ('Ginger' if o2 else 'none'))
                    print(f"[status] door={door_state} ({open_pct}%) | switch={sw_str} | owners={avail_str}")
                    last_status = now

            time.sleep(0.2)

    except KeyboardInterrupt:
        print("Shutting down")
    finally:
        stop()
        for pwm in _led_pwm.values():
            pwm.ChangeDutyCycle(0)
            pwm.stop()
        GPIO.cleanup([IN1, IN2, ENA, SW_OPEN, SW_CLOSE,
                      LED_OPEN, LED_CLOSED, LED_COUNTDOWN, LED_OWNER1, LED_OWNER2])
        os._exit(0)


if __name__ == '__main__':
    main()
