import RPi.GPIO as GPIO
import math
import time
import os
import threading
import signal

BTN_RESTART      = 24
BTN_REBOOT       = 25
BUZZER_PIN       = 23
REBOOT_HOLD_SECS = 3
FIREBASE_KEY     = '/home/pat0222/dog-door/firebase-key.json'
FIREBASE_URL     = 'https://dog-door-632e6-default-rtdb.firebaseio.com/'
STATE_FILE       = '/home/pat0222/dog-door/.door_state'
BEEP_FILE        = '/home/pat0222/dog-door/.beep_request'

_firebase_lock   = threading.Lock()
_owner_available = [True, True]
_oled_stop       = False
_oled_device     = None
_oled_font_large = None
_oled_font_huge  = None
_oled_override   = False
_buzzer_lock     = threading.Lock()

# Beep patterns: (on_secs, off_secs) — active buzzer, GPIO toggle only
BEEP_OPEN     = [(0.1, 0.05), (0.15, 0)]
BEEP_CLOSE    = [(0.15, 0.05), (0.1, 0)]
BEEP_STUCK    = [(0.05, 0.05)] * 3
BEEP_RESTART  = [(0.1, 0.05), (0.1, 0)]
BEEP_REBOOT   = [(0.2, 0.1)] * 3
BEEP_SHUTDOWN = [(0.4, 0)]


def get_wifi_dbm():
    try:
        with open('/proc/net/wireless') as f:
            for line in f:
                if 'wlan0' in line:
                    parts = line.split()
                    return int(float(parts[3].rstrip('.')))
    except Exception:
        return None


def read_door_state():
    try:
        with open(STATE_FILE) as f:
            parts = f.read().strip().split()
        state = parts[0] if parts else 'closed'
        if state == 'open':
            pos = 0.0
        elif state == 'closed':
            pos = 1.0
        elif len(parts) == 2:
            pos = float(parts[1])
        else:
            pos = 0.5
        return state, round((1.0 - pos) * 100)
    except Exception:
        return 'unknown', 0


def beep(pattern):
    def _do():
        if not _buzzer_lock.acquire(blocking=False):
            return
        try:
            for on_secs, off_secs in pattern:
                GPIO.output(BUZZER_PIN, GPIO.HIGH)
                time.sleep(on_secs)
                GPIO.output(BUZZER_PIN, GPIO.LOW)
                if off_secs > 0:
                    time.sleep(off_secs)
        finally:
            _buzzer_lock.release()
    threading.Thread(target=_do, daemon=True).start()


def poll_beep_request():
    try:
        with open(BEEP_FILE) as f:
            req = f.read().strip()
        os.remove(BEEP_FILE)
        if req == 'open':
            beep(BEEP_OPEN)
        elif req == 'close':
            beep(BEEP_CLOSE)
        elif req == 'stuck':
            beep(BEEP_STUCK)
    except FileNotFoundError:
        pass
    except Exception:
        pass


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

    if build < 0.18:
        br = int(22 * build / 0.18)
        draw.ellipse([cx-br, gy-br//3, cx+br, gy+1], fill="white")

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
            if wifi is None:
                blink = int(time.monotonic() * 2) % 2 == 0
                with canvas(device) as draw:
                    if blink:
                        draw.text((10, 20), "NO WIFI", font=_oled_font_large, fill="white")
                time.sleep(0.25)
                continue
            state, pct = read_door_state()
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
            wifi_str = f"WiFi: {wifi} dBm"

            with canvas(device) as draw:
                draw.text((0,  0), state_label, fill="white")
                draw.text((0, 16), f"Open: {pct}%", fill="white")
                draw.text((0, 32), owner_str,        fill="white")
                draw.text((0, 48), wifi_str,          fill="white")
        except Exception:
            pass
        time.sleep(1)


def init_firebase():
    try:
        import firebase_admin
        from firebase_admin import credentials, db
        cred = credentials.Certificate(FIREBASE_KEY)
        firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_URL})

        def make_owner_listener(idx):
            def on_owner(event):
                if isinstance(event.data, dict):
                    with _firebase_lock:
                        _owner_available[idx] = bool(event.data.get('available', True))
            return on_owner

        db.reference('owners/owner1').listen(make_owner_listener(0))
        db.reference('owners/owner2').listen(make_owner_listener(1))
        print("Firebase connected (owners)")
    except Exception as e:
        print(f"Firebase unavailable: {e} — owner display will use defaults")


def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(BTN_RESTART, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(BTN_REBOOT,  GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(BUZZER_PIN,  GPIO.OUT, initial=GPIO.LOW)


def main():
    global _oled_stop

    setup_gpio()
    threading.Thread(target=init_firebase, daemon=True).start()
    threading.Thread(target=oled_loop, daemon=True).start()

    print("Peripheral controller ready")

    restart_press_start = None
    reboot_press_start  = None
    both_hold_start     = None

    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))

    try:
        while True:
            poll_beep_request()

            btn_restart = not GPIO.input(BTN_RESTART)
            btn_reboot  = not GPIO.input(BTN_REBOOT)

            if btn_restart and btn_reboot:
                restart_press_start = None
                reboot_press_start  = None
                if both_hold_start is None:
                    both_hold_start = time.monotonic()
                elif time.monotonic() - both_hold_start >= 2.0:
                    print("Both buttons held — shutting down")
                    beep(BEEP_SHUTDOWN)
                    if oled_shutdown_countdown():
                        os.system("sudo shutdown -h now")
                    else:
                        both_hold_start = None
            else:
                both_hold_start = None

                if btn_restart:
                    if restart_press_start is None:
                        restart_press_start = time.monotonic()
                    elif time.monotonic() - restart_press_start >= 1.0:
                        print("Restart button — restarting dog-door service")
                        beep(BEEP_RESTART)
                        oled_scroll("RESTARTING DOG DOOR SERVICE", duration=2.0, font=_oled_font_large)
                        if _oled_device:
                            try:
                                from luma.core.render import canvas as luma_canvas
                                with luma_canvas(_oled_device) as draw:
                                    draw.text((4, 20), "RESTARTING...", fill="white", font=_oled_font_large)
                            except Exception:
                                pass
                        time.sleep(0.3)
                        os.system("sudo systemctl restart dog-door")
                        restart_press_start = None
                else:
                    restart_press_start = None

                if btn_reboot:
                    if reboot_press_start is None:
                        reboot_press_start = time.monotonic()
                    elif time.monotonic() - reboot_press_start >= REBOOT_HOLD_SECS:
                        print("Reboot button held — rebooting Pi")
                        beep(BEEP_REBOOT)
                        if oled_reboot_countdown():
                            os.system("sudo reboot")
                        else:
                            reboot_press_start = None
                else:
                    reboot_press_start = None

            time.sleep(0.2)

    except KeyboardInterrupt:
        print("Peripheral controller shutting down")
    finally:
        _oled_stop = True
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        GPIO.cleanup([BTN_RESTART, BTN_REBOOT, BUZZER_PIN])
        os._exit(0)


if __name__ == '__main__':
    main()
