import RPi.GPIO as GPIO
# from mfrc522 import MFRC522, SimpleMFRC522  # UHF RFID upgrade pending — see README
import math
import time
import os
import threading
import json
import urllib.request
import signal

# --- RFID tag IDs (reserved for UHF RFID upgrade) ---
# AUTHORIZED_TAGS  = {613025449752, 372068189196}
# READER1_HOME_TAG = 613025449752
# READER2_HOME_TAG = 372068189196

# GPIO pins (BCM)
IN1 = 17
IN2 = 27
ENA = 22
SW_OPEN  = 5    # GPIO5 (Pin 29) — manual switch +VE(Load) — retracts actuator, opens door
SW_CLOSE = 6    # GPIO6 (Pin 31) — manual switch -VE(Load) — extends actuator, closes door

# LED pins (BCM) — driven via 2N2222 NPN transistors from 12V
LED_OPEN      = 12  # GPIO12 (Pin 32) — green
LED_CLOSED    = 13  # GPIO13 (Pin 33) — red
LED_COUNTDOWN = 16  # GPIO16 (Pin 36) — amber
LED_OWNER1    = 20  # GPIO20 (Pin 38) — blue (Rita)
LED_OWNER2    = 26  # GPIO26 (Pin 37) — white (Ginger)

# Buzzer pin (BCM)
BUZZER_PIN = 23  # GPIO23 (Pin 16) — passive buzzer

# Button pins (BCM) — active LOW with internal pull-up
BTN_RESTART = 24  # GPIO24 — service restart (short press)
BTN_REBOOT  = 25  # GPIO25 — Pi reboot (hold 3s)

# Timing
CLOSE_DELAY_SECS  = 10
REBOOT_HOLD_SECS  = 3
ACTUATOR_TRAVEL_SECS = 7.84
STATUS_INTERVAL = 2
STUCK_ALERT_SECS = 900   # 15 minutes in a partial state triggers flashing LEDs

# Door states
OPEN             = 'open'
CLOSED           = 'closed'
PARTIALLY_OPEN   = 'partially_open'
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
_firebase_connected = False
_startup_time = time.monotonic()

_buzzer_pwm  = None
_buzzer_lock = threading.Lock()

_oled_stop = False
_oled_device = None
_oled_font_large = None   # loaded once by oled_loop
_oled_font_huge  = None
_oled_override   = False  # when True, oled_loop skips normal rendering
_restart_requested = False

# Beep patterns: list of (frequency_hz, on_secs, off_secs)
BEEP_OPEN  = [(1000, 0.1, 0.05), (1200, 0.15, 0)]
BEEP_CLOSE = [(1200, 0.1, 0.05), (1000, 0.15, 0)]
BEEP_STUCK = [(2000, 0.05, 0.05)] * 3


def get_wifi_dbm():
    try:
        with open('/proc/net/wireless') as f:
            for line in f:
                if 'wlan0' in line:
                    parts = line.split()
                    return int(float(parts[3].rstrip('.')))
    except Exception:
        return None


def _draw_flame_lick(draw, bx, by, angle, length, width):
    local_pts = [
        (0, -width/2), (length*0.25, -width/2.2), (length*0.6, -width/4),
        (length, 0),
        (length*0.6, width/4), (length*0.25, width/2.2), (0, width/2),
    ]
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    pts = [(int(bx + lx*cos_a - ly*sin_a), int(by + lx*sin_a + ly*cos_a))
           for lx, ly in local_pts]
    draw.polygon(pts, fill="white")


def _draw_mushroom(draw, progress):
    cx, gy = 64, 62
    p = max(0.0, min(2.0, progress))
    build  = min(1.0, p)
    dissip = max(0.0, p - 1.0)

    # Ground blast
    if build < 0.18:
        br = int(22 * build / 0.18)
        draw.ellipse([cx-br, gy-br//3, cx+br, gy+1], fill="white")

    # Base skirt + ground flame licks
    if build > 0.06:
        bp = min(1.0, (build - 0.06) / 0.25)
        br2 = int((16 + dissip*10) * bp)
        draw.ellipse([cx-br2, gy-5, cx+br2, gy+1], fill="white")
        if build > 0.1:
            for i in range(10):
                ang = math.pi * i / 9
                ex = cx + int(br2 * math.cos(ang))
                ey = gy - int(br2 * 0.4 * math.sin(ang))
                fl = int((5 + 6*abs(math.sin(i*1.3+0.7))) * bp)
                fw = int((3 + 2*abs(math.sin(i*0.9+1.2))) * bp)
                if fl > 1 and fw > 1:
                    _draw_flame_lick(draw, ex, ey, ang - math.pi/2, fl, fw)

    # Stem + side flame licks
    if build > 0.12:
        sp = min(1.0, (build - 0.12) / 0.45)
        sh = int((38 + dissip*6) * sp)
        stem_top = gy - sh
        sw_b = max(2, int(6 - dissip*3))
        sw_t = max(1, int(3 - dissip*1.5))
        if sh > 0:
            draw.polygon([(cx-sw_b,gy),(cx+sw_b,gy),(cx+sw_t,stem_top),(cx-sw_t,stem_top)], fill="white")
            for i in range(5):
                frac = 0.12 + i*0.18
                sy = gy - int(sh * frac)
                sw_here = sw_b - int((sw_b - sw_t) * frac)
                fl = int((5 + 4*abs(math.sin(i*2.1+0.5))) * sp)
                fw = int((2 + 2*abs(math.sin(i*1.7+1.0))) * sp)
                if fl > 1 and fw > 1:
                    _draw_flame_lick(draw, cx-sw_here, sy, math.pi, fl, fw)
                    _draw_flame_lick(draw, cx+sw_here, sy, 0,       fl, fw)
    else:
        stem_top = gy

    # Cap + perimeter flame licks
    if build > 0.42:
        cp = min(1.0, (build - 0.42) / 0.58)
        cap_rx = int(44 * cp * (1 + dissip*0.65))
        cap_ry = int(17 * cp * (1 + dissip*0.25))
        cap_cy = stem_top - cap_ry + int(dissip*3)

        if cap_rx > 1:
            draw.ellipse([cx-cap_rx, cap_cy-cap_ry, cx+cap_rx, cap_cy+cap_ry], fill="white")

            n = 12
            for i in range(n):
                ang = math.radians(-150 + (i/(n-1))*300)
                ex = cx + int(cap_rx * math.cos(ang))
                ey = cap_cy + int(cap_ry * math.sin(ang))
                fl = int((6 + 9*abs(math.cos(ang*1.5+0.4))) * cp)
                fw = int((3 + 3*abs(math.sin(i*1.2+0.8))) * cp)
                if fl > 1 and fw > 1:
                    _draw_flame_lick(draw, ex, ey, ang, fl, fw)
                    if i % 2 == 0:
                        ang2 = ang + math.radians(8)
                        ex2 = cx + int(cap_rx * math.cos(ang2))
                        ey2 = cap_cy + int(cap_ry * math.sin(ang2))
                        _draw_flame_lick(draw, ex2, ey2, ang2, fl//2, fw//2)

            if dissip > 0.15:
                hp = min(1.0, (dissip - 0.15) / 0.55)
                irx = int(cap_rx * 0.55 * hp)
                iry = int(cap_ry * 0.45 * hp)
                if irx > 1 and iry > 1:
                    draw.ellipse([cx-irx, cap_cy-iry, cx+irx, cap_cy+iry], fill="black")


def _draw_poop(draw, blink=False):
    cx = 64
    draw.ellipse([cx-28, 50, cx+28, 64], fill="white")
    draw.ellipse([cx-21, 38, cx+21, 56], fill="white")
    draw.ellipse([cx-14, 27, cx+14, 43], fill="white")
    draw.ellipse([cx-8,  17, cx+8,  30], fill="white")
    ey = 43
    if not blink:
        draw.ellipse([cx-14, ey-5, cx-7,  ey+2], fill="black")
        draw.ellipse([cx+7,  ey-5, cx+14, ey+2], fill="black")
    else:
        draw.line([cx-14, ey-2, cx-7,  ey-2], fill="black", width=2)
        draw.line([cx+7,  ey-2, cx+14, ey-2], fill="black", width=2)
    draw.arc([cx-12, ey-2, cx+12, ey+10], start=20, end=160, fill="black", width=2)


def oled_poop_animation():
    if _oled_device is None:
        time.sleep(2)
        return
    try:
        from luma.core.render import canvas as luma_canvas
        for blink in [False, False, False, True, False, False, False, True, False, False]:
            with luma_canvas(_oled_device) as draw:
                _draw_poop(draw, blink=blink)
            time.sleep(0.3 if not blink else 0.15)
    except Exception:
        time.sleep(2)


def oled_shutdown_countdown():
    global _oled_override
    _oled_override = True
    try:
        oled_scroll("SHUTTING DOWN IN", duration=1.5, font=_oled_font_large, manage_flag=False)
        if _oled_device is None:
            time.sleep(5)
            return True
        from luma.core.render import canvas as luma_canvas
        f = _oled_font_huge
        for _ in range(40):
            if GPIO.input(BTN_RESTART) and GPIO.input(BTN_REBOOT):
                break
            time.sleep(0.05)
        cancelled = False
        for n in range(5, 0, -1):
            s = str(n)
            w = _oled_text_width(s, f) if f else 30
            fh = (f.size if hasattr(f, 'size') else 52) if f else 52
            x = (128 - w) // 2
            y = (64 - fh) // 2
            with luma_canvas(_oled_device) as draw:
                draw.text((x, y), s, fill="white", font=f)
            for _ in range(20):
                time.sleep(0.05)
                if not GPIO.input(BTN_RESTART) or not GPIO.input(BTN_REBOOT):
                    cancelled = True
                    break
            if cancelled:
                break
        if not cancelled:
            oled_poop_animation()
        else:
            oled_scroll("SHUTDOWN CANCELLED", duration=1.5, font=_oled_font_large, manage_flag=False)
        return not cancelled
    except Exception:
        time.sleep(5)
        return True
    finally:
        _oled_override = False


def oled_mushroom_animation():
    if _oled_device is None:
        time.sleep(4)
        return
    try:
        from luma.core.render import canvas as luma_canvas
        for i in range(16):
            with luma_canvas(_oled_device) as draw:
                _draw_mushroom(draw, i / 15)
            time.sleep(0.03)
        for _ in range(2):
            with luma_canvas(_oled_device) as draw:
                _draw_mushroom(draw, 1.0)
            time.sleep(0.05)
        for i in range(12):
            with luma_canvas(_oled_device) as draw:
                _draw_mushroom(draw, 1.0 + i / 11)
            time.sleep(0.03)
    except Exception:
        time.sleep(6)


def _oled_text_width(text, font):
    try:
        return int(font.getlength(text))
    except AttributeError:
        return font.getsize(text)[0]


def oled_scroll(text, duration=1.5, font=None, manage_flag=True):
    global _oled_override
    if _oled_device is None:
        time.sleep(duration)
        return
    if manage_flag:
        _oled_override = True
    try:
        from luma.core.render import canvas as luma_canvas
        f = font or _oled_font_large
        w = _oled_text_width(text, f) if f else len(text) * 8
        fh = (f.size if hasattr(f, 'size') else 16) if f else 16
        y = (64 - fh) // 2
        start_x, end_x = 128, -w
        frames = max(1, int(duration / 0.04))
        for i in range(frames):
            x = int(start_x - (start_x - end_x) * i / frames)
            with luma_canvas(_oled_device) as draw:
                draw.text((x, y), text, fill="white", font=f)
            time.sleep(duration / frames)
    except Exception:
        time.sleep(duration)
    finally:
        if manage_flag:
            _oled_override = False


def oled_reboot_countdown():
    global _oled_override
    _oled_override = True
    try:
        oled_scroll("REBOOTING PI IN", duration=1.5, font=_oled_font_large, manage_flag=False)
        if _oled_device is None:
            time.sleep(5)
            return True
        from luma.core.render import canvas as luma_canvas
        f = _oled_font_huge
        # Wait for button to be released before watching for cancel press
        for _ in range(40):
            if GPIO.input(BTN_REBOOT):
                break
            time.sleep(0.05)
        cancelled = False
        for n in range(5, 0, -1):
            s = str(n)
            w = _oled_text_width(s, f) if f else 30
            fh = (f.size if hasattr(f, 'size') else 52) if f else 52
            x = (128 - w) // 2
            y = (64 - fh) // 2
            with luma_canvas(_oled_device) as draw:
                draw.text((x, y), s, fill="white", font=f)
            for _ in range(20):
                time.sleep(0.05)
                if not GPIO.input(BTN_REBOOT):
                    cancelled = True
                    break
            if cancelled:
                break
        if not cancelled:
            oled_mushroom_animation()
        else:
            oled_scroll("REBOOT CANCELLED", duration=1.5, font=_oled_font_large, manage_flag=False)
        return not cancelled
    except Exception:
        time.sleep(5)
        return True
    finally:
        _oled_override = False


def _load_font(size):
    from PIL import ImageFont
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def oled_loop():
    global _oled_device, _oled_font_large, _oled_font_huge
    try:
        from luma.core.interface.serial import i2c as luma_i2c
        from luma.oled.device import ssd1306
        from luma.core.render import canvas
        serial = luma_i2c(port=1, address=0x3C)
        device = ssd1306(serial)
        _oled_device = device
        _oled_font_large = _load_font(28)
        _oled_font_huge  = _load_font(52)
    except Exception as e:
        print(f"OLED unavailable: {e}")
        return

    print("OLED ready")
    while not _oled_stop:
        if _oled_override:
            time.sleep(0.05)
            continue
        try:
            wifi = get_wifi_dbm()
            state = door_state
            pct = round((1.0 - actuator_pos) * 100)
            with _firebase_lock:
                o1 = _owner_available[0]
                o2 = _owner_available[1]

            if o1 and o2:
                owner_str = "Owners: both"
            elif o1:
                owner_str = "Owners: Rita"
            elif o2:
                owner_str = "Owners: Ginger"
            else:
                owner_str = "Owners: away"

            state_label = state.replace('_', ' ').upper()
            wifi_str = f"WiFi: {wifi} dBm" if wifi is not None else "WiFi: N/A"

            with canvas(device) as draw:
                draw.text((0,  0), state_label, fill="white")
                draw.text((0, 16), f"Open: {pct}%", fill="white")
                draw.text((0, 32), owner_str,        fill="white")
                draw.text((0, 48), wifi_str,          fill="white")
        except Exception:
            pass
        time.sleep(1)


def beep_pattern(pattern):
    def _do():
        if not _buzzer_lock.acquire(blocking=False):
            return
        try:
            for freq, on, off in pattern:
                _buzzer_pwm.ChangeFrequency(freq)
                _buzzer_pwm.start(50)
                time.sleep(on)
                _buzzer_pwm.stop()
                if off > 0:
                    time.sleep(off)
        finally:
            _buzzer_lock.release()
    threading.Thread(target=_do, daemon=True).start()


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
                        db.reference('command').set(None)
                    except Exception:
                        pass
                else:
                    with _firebase_lock:
                        _firebase_command = event.data

        db.reference('owners/owner1').listen(make_owner_listener(0))
        db.reference('owners/owner2').listen(make_owner_listener(1))
        db.reference('command').listen(on_command)
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
    global _buzzer_pwm
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(IN1, GPIO.OUT)
    GPIO.setup(IN2, GPIO.OUT)
    GPIO.setup(ENA, GPIO.OUT)
    GPIO.setup(SW_OPEN,  GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    GPIO.setup(SW_CLOSE, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    GPIO.setup(LED_OPEN,      GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(LED_CLOSED,    GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(LED_COUNTDOWN, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(LED_OWNER1,    GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(LED_OWNER2,    GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(BUZZER_PIN, GPIO.OUT, initial=GPIO.LOW)
    _buzzer_pwm = GPIO.PWM(BUZZER_PIN, 1000)
    GPIO.setup(BTN_RESTART, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(BTN_REBOOT,  GPIO.IN, pull_up_down=GPIO.PUD_UP)
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
    in_grace = time.monotonic() - _startup_time < 5
    if not _firebase_connected and not in_grace:
        # Chase pattern: one LED at a time cycling green→amber→red→blue→white
        slot = int(time.monotonic() / 0.3) % len(_LED_SEQUENCE)
        for i, pin in enumerate(_LED_SEQUENCE):
            GPIO.output(pin, GPIO.HIGH if i == slot else GPIO.LOW)
        return

    blink = int(time.monotonic() * 2) % 2 == 0
    if stuck_alert:
        # All three flash together when door is stuck in a partial state
        state = GPIO.HIGH if blink else GPIO.LOW
        GPIO.output(LED_OPEN,      state)
        GPIO.output(LED_CLOSED,    state)
        GPIO.output(LED_COUNTDOWN, state)
    else:
        # Green flashes while opening, solid when fully open
        if door_state == PARTIALLY_OPEN:
            GPIO.output(LED_OPEN, GPIO.HIGH if blink else GPIO.LOW)
        else:
            GPIO.output(LED_OPEN, GPIO.HIGH if is_open() else GPIO.LOW)
        # Red flashes while closing, solid when fully closed
        if door_state == PARTIALLY_CLOSED:
            GPIO.output(LED_CLOSED, GPIO.HIGH if blink else GPIO.LOW)
        else:
            GPIO.output(LED_CLOSED, GPIO.HIGH if is_closed() else GPIO.LOW)
        GPIO.output(LED_COUNTDOWN, GPIO.HIGH if countdown_active else GPIO.LOW)

    # Owner LEDs always reflect current availability
    with _firebase_lock:
        GPIO.output(LED_OWNER1, GPIO.HIGH if _owner_available[0] else GPIO.LOW)
        GPIO.output(LED_OWNER2, GPIO.HIGH if _owner_available[1] else GPIO.LOW)


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
        update_leds(False, False)
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


def close_door():
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
        update_leds(False, False)
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
        # --- RFID reverse-on-tag logic (reserved for UHF RFID upgrade) ---
        # per_reader = scan_tags_per_reader(reader1, reader2)
        # if home_tag and home_tag[0] is not None:
        #     reverse = (
        #         (per_reader[0] is not None and per_reader[0] != home_tag[0]) or
        #         (per_reader[1] is not None and per_reader[1] != home_tag[1])
        #     )
        # else:
        #     reverse = any(t is not None for t in per_reader)
        # if reverse:
        #     print("Tag on wrong side during close — reversing")
        #     stop()
        #     actuator_pos = min(1.0, actuator_pos + (time.monotonic() - start) / ACTUATOR_TRAVEL_SECS)
        #     time.sleep(0.2)
        #     open_door()
        #     closing = False
        #     return False
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
        update_leds(False, False)
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
        update_leds(False, False)
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


# --- RFID scan functions (reserved for UHF RFID upgrade) ---
# def scan_tags_per_reader(reader1, reader2):
#     result = []
#     for reader in [reader1, reader2]:
#         tag = None
#         (status, _) = reader.READER.MFRC522_Request(reader.READER.PICC_REQALL)
#         if status == reader.READER.MI_OK:
#             (status, uid) = reader.READER.MFRC522_Anticoll()
#             if status == reader.READER.MI_OK:
#                 t = 0
#                 for byte in uid:
#                     t = t * 256 + byte
#                 if t in AUTHORIZED_TAGS:
#                     tag = t
#         reader.READER.MFRC522_Init()
#         result.append(tag)
#     return result  # [tag_at_reader1|None, tag_at_reader2|None]
#
# def scan_tags(reader1, reader2):
#     return {t for t in scan_tags_per_reader(reader1, reader2) if t is not None}


def main():
    global closing, _restart_requested

    setup_gpio()
    init_firebase()

    # --- RFID reader initialization (reserved for UHF RFID upgrade) ---
    # rfid1 = MFRC522(bus=0, device=0, pin_rst=25)
    # rfid2 = MFRC522(bus=0, device=1, pin_rst=24)
    # reader1 = SimpleMFRC522()
    # reader1.READER = rfid1
    # reader2 = SimpleMFRC522()
    # reader2.READER = rfid2

    threading.Thread(target=oled_loop, daemon=True).start()

    print(f"Dog door ready — state: {door_state}")

    prev_sw_open        = False
    prev_sw_close       = False
    last_status         = 0
    last_stuck_beep     = 0
    restart_press_start = None
    reboot_press_start  = None
    both_hold_start     = None
    partial_since       = time.monotonic() if door_state in (PARTIALLY_OPEN, PARTIALLY_CLOSED) else None

    # --- RFID tracking state (reserved for UHF RFID upgrade) ---
    # home_tag           = [None, None]
    # last_seen          = [None, None]
    # home_detected_time = [None, None]
    # close_deadline     = None

    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))

    try:
        while True:
            sw_open  = GPIO.input(SW_OPEN)
            sw_close = GPIO.input(SW_CLOSE)

            # Manual switch takes priority — act only on rising edge
            if sw_open and not prev_sw_open and door_state != OPEN and not closing:
                print("Manual switch — opening door")
                if open_door_manual():
                    beep_pattern(BEEP_OPEN)
                    send_push_notification("Puppy Play Time", "Door opened manually.")
            elif sw_close and not prev_sw_close and door_state != CLOSED and not closing:
                print("Manual switch — closing door")
                if close_door_manual():
                    beep_pattern(BEEP_CLOSE)
                    send_push_notification("Puppy Play Time", "Door closed manually.")

            prev_sw_open  = sw_open
            prev_sw_close = sw_close

            btn_restart = not GPIO.input(BTN_RESTART)
            btn_reboot  = not GPIO.input(BTN_REBOOT)

            # Both buttons held — shutdown
            if btn_restart and btn_reboot:
                restart_press_start = None
                reboot_press_start  = None
                if both_hold_start is None:
                    both_hold_start = time.monotonic()
                elif time.monotonic() - both_hold_start >= 2.0:
                    print("Both buttons held — shutting down")
                    beep_pattern([(600, 0.4, 0)])
                    if oled_shutdown_countdown():
                        os.system("sudo shutdown -h now")
                    else:
                        both_hold_start = None
            else:
                both_hold_start = None

                # Service restart button — hold 1s to trigger
                if btn_restart:
                    if restart_press_start is None:
                        restart_press_start = time.monotonic()
                    elif time.monotonic() - restart_press_start >= 1.0:
                        print("Restart button held — restarting service")
                        beep_pattern([(1000, 0.1, 0.05), (1000, 0.1, 0)])
                        oled_scroll("RESTARTING DOG DOOR SERVICE", duration=2.0, font=_oled_font_large)
                        if _oled_device:
                            try:
                                from luma.core.render import canvas as luma_canvas
                                with luma_canvas(_oled_device) as draw:
                                    draw.text((4, 20), "RESTARTING...", fill="white", font=_oled_font_large)
                            except Exception:
                                pass
                        time.sleep(0.3)
                        _restart_requested = True
                else:
                    restart_press_start = None

                # Reboot button — hold for REBOOT_HOLD_SECS
                if btn_reboot:
                    if reboot_press_start is None:
                        reboot_press_start = time.monotonic()
                    elif time.monotonic() - reboot_press_start >= REBOOT_HOLD_SECS:
                        print("Reboot button held — rebooting Pi")
                        beep_pattern([(500, 0.2, 0.1)] * 3)
                        if oled_reboot_countdown():
                            os.system("sudo reboot")
                        else:
                            reboot_press_start = None
                else:
                    reboot_press_start = None

            if _restart_requested:
                raise KeyboardInterrupt

            if not closing:
                # Handle app commands
                cmd = poll_firebase_command()
                if cmd == 'open' and door_state != OPEN and both_owners_available():
                    print("App command — opening door")
                    if open_door():
                        beep_pattern(BEEP_OPEN)
                        send_push_notification("Puppy Play Time", "Door opened via app.")
                elif cmd == 'close' and door_state != CLOSED:
                    print("App command — closing door")
                    if close_door():
                        beep_pattern(BEEP_CLOSE)
                        send_push_notification("Puppy Play Time", "Door closed via app.")

                # --- RFID open trigger (reserved for UHF RFID upgrade) ---
                # per_reader = scan_tags_per_reader(reader1, reader2)
                # if is_closed():
                #     if (per_reader[0] is not None and per_reader[1] is not None
                #             and per_reader[0] != per_reader[1]
                #             and both_owners_available()):
                #         print("Both tags on opposite sides — opening door")
                #         home_tag[:] = per_reader
                #         last_seen[:] = [None, None]
                #         home_detected_time[:] = [None, None]
                #         close_deadline = None
                #         if open_door():
                #             send_push_notification("Puppy Play Time", "Door opened — the dogs are playing.")

                # --- RFID auto-close trigger (reserved for UHF RFID upgrade) ---
                # elif is_open():
                #     for i, tag in enumerate(per_reader):
                #         if tag is not None:
                #             last_seen[i] = tag
                #             if home_tag[i] is not None and tag == home_tag[i]:
                #                 home_detected_time[i] = time.monotonic()
                #     cross_detected = home_tag[0] is not None and (
                #         (per_reader[0] is not None and per_reader[0] != home_tag[0]) or
                #         (per_reader[1] is not None and per_reader[1] != home_tag[1])
                #     )
                #     either_home = (home_tag[0] is not None
                #                    and any(t is not None for t in home_detected_time))
                #     if either_home and not cross_detected:
                #         if close_deadline is None:
                #             print(f"Dog home detected — closing in {CLOSE_DELAY_SECS}s")
                #             close_deadline = time.monotonic() + CLOSE_DELAY_SECS
                #         elif time.monotonic() >= close_deadline:
                #             close_deadline = None
                #             if close_door():
                #                 send_push_notification("Puppy Play Time", "Dogs are home. Door closed.")
                #     else:
                #         if close_deadline is not None:
                #             print("Dog activity detected — cancelling close")
                #         close_deadline = None
                #         if cross_detected:
                #             home_detected_time[:] = [None, None]

                # Track how long door has been in a partial state
                if door_state in (PARTIALLY_OPEN, PARTIALLY_CLOSED):
                    if partial_since is None:
                        partial_since = time.monotonic()
                else:
                    partial_since = None
                stuck_alert = (partial_since is not None
                               and time.monotonic() - partial_since >= STUCK_ALERT_SECS)
                if stuck_alert and time.monotonic() - last_stuck_beep >= 30:
                    beep_pattern(BEEP_STUCK)
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
        global _oled_stop
        _oled_stop = True
        stop()
        if _buzzer_pwm:
            _buzzer_pwm.stop()
        for pin in (LED_OPEN, LED_CLOSED, LED_COUNTDOWN, LED_OWNER1, LED_OWNER2):
            GPIO.output(pin, GPIO.LOW)
        # --- RFID cleanup (reserved for UHF RFID upgrade) ---
        # try:
        #     rfid1.spi.close()
        #     rfid2.spi.close()
        # except Exception:
        #     pass
        GPIO.cleanup()
        os._exit(0)


if __name__ == '__main__':
    main()
