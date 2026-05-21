import RPi.GPIO as GPIO
from mfrc522 import MFRC522, SimpleMFRC522
import time

# RFID tag IDs
AUTHORIZED_TAGS = {613025449752, 372068189196}

# GPIO pins (BCM)
IN1 = 17
IN2 = 27
ENA = 22
SW_EXTEND = 5   # GPIO5 (Pin 29) — manual switch +VE(Load)
SW_RETRACT = 6  # GPIO6 (Pin 31) — manual switch -VE(Load)

# Timing
CLOSE_DELAY_SECS = 10
ACTUATOR_TRAVEL_SECS = 8
STATUS_INTERVAL = 2

# State
door_open = False
closing = False


def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(IN1, GPIO.OUT)
    GPIO.setup(IN2, GPIO.OUT)
    GPIO.setup(ENA, GPIO.OUT)
    GPIO.setup(SW_EXTEND, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    GPIO.setup(SW_RETRACT, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    stop()


def extend():
    print("Opening door...")
    GPIO.output(IN1, GPIO.LOW)
    GPIO.output(IN2, GPIO.HIGH)
    GPIO.output(ENA, GPIO.HIGH)


def retract():
    print("Closing door...")
    GPIO.output(IN1, GPIO.HIGH)
    GPIO.output(IN2, GPIO.LOW)
    GPIO.output(ENA, GPIO.HIGH)


def stop():
    GPIO.output(ENA, GPIO.LOW)


def open_door():
    global door_open
    retract()
    time.sleep(ACTUATOR_TRAVEL_SECS)
    stop()
    door_open = True
    print("Door open")


def close_door(reader1, reader2):
    global door_open, closing
    closing = True
    door_open = False
    print("Closing in progress...")
    extend()
    for _ in range(ACTUATOR_TRAVEL_SECS * 10):
        time.sleep(0.1)
        tags = scan_tags(reader1, reader2)
        if tags:
            print("Tag detected during close — reversing")
            stop()
            time.sleep(0.2)
            open_door()
            closing = False
            return
    stop()
    closing = False
    print("Door closed")


def open_door_manual():
    global door_open, closing
    closing = True
    print("Manual open in progress...")
    retract()
    for _ in range(ACTUATOR_TRAVEL_SECS * 10):
        time.sleep(0.1)
        if not GPIO.input(SW_EXTEND):
            stop()
            if GPIO.input(SW_RETRACT):
                print("Manual switch reversed — closing")
                time.sleep(0.1)
                close_door_manual()
            else:
                print("Manual open stopped")
                door_open = False
                closing = False
            return
    stop()
    door_open = True
    closing = False
    print("Door open (manual)")


def close_door_manual():
    global door_open, closing
    closing = True
    print("Manual close in progress...")
    extend()
    for _ in range(ACTUATOR_TRAVEL_SECS * 10):
        time.sleep(0.1)
        if not GPIO.input(SW_RETRACT):
            stop()
            if GPIO.input(SW_EXTEND):
                print("Manual switch reversed — opening")
                time.sleep(0.1)
                open_door_manual()
            else:
                print("Manual close stopped")
                door_open = True
                closing = False
            return
    stop()
    door_open = False
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
    global door_open, closing

    setup_gpio()

    rfid1 = MFRC522(bus=0, device=0, pin_rst=25)
    rfid2 = MFRC522(bus=0, device=1, pin_rst=24)

    reader1 = SimpleMFRC522()
    reader1.READER = rfid1

    reader2 = SimpleMFRC522()
    reader2.READER = rfid2

    print("Dog door ready — polling...")

    prev_sw_extend = False
    prev_sw_retract = False
    last_status = 0

    try:
        while True:
            sw_extend = GPIO.input(SW_EXTEND)
            sw_retract = GPIO.input(SW_RETRACT)

            # Manual switch takes priority — act only on rising edge
            if sw_extend and not prev_sw_extend and not door_open and not closing:
                print("Manual switch — opening door")
                open_door_manual()
            elif sw_retract and not prev_sw_retract and door_open and not closing:
                print("Manual switch — closing door")
                close_door_manual()

            prev_sw_extend = sw_extend
            prev_sw_retract = sw_retract

            if not closing:
                tags = scan_tags(reader1, reader2)

                if not door_open:
                    if len(tags) == 2:
                        print("Both tags detected — opening door")
                        open_door()

                elif door_open:
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
                    sw_str = 'extend' if sw_extend else ('retract' if sw_retract else 'neutral')
                    print(f"[status] door={'open' if door_open else 'closed'} | tags={tag_str} | switch={sw_str}")
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
