#!/usr/bin/env python3
"""
Test 12: HD44780 16x2 LCD Display (4-bit GPIO Mode)
===================================================
Tests 4-bit parallel display control on 16x2 character LCD.

Wiring:
    - VSS (Pin 1 on LCD) -> GND (Pin 6)
    - VDD (Pin 2 on LCD) -> 5V (Pin 2)
    - V0  (Pin 3 on LCD) -> 10k Potentiometer wiper or 1k resistor to GND (Contrast)
    - RS  (Pin 4 on LCD) -> GPIO 21 (Pin 40)
    - RW  (Pin 5 on LCD) -> GND (Pin 39) - Write mode only
    - E   (Pin 6 on LCD) -> GPIO 22 (Pin 15)
    - D4  (Pin 11 on LCD) -> GPIO 23 (Pin 16)
    - D5  (Pin 12 on LCD) -> GPIO 24 (Pin 18)
    - D6  (Pin 13 on LCD) -> GPIO 25 (Pin 22)
    - D7  (Pin 14 on LCD) -> GPIO 26 (Pin 37)
    - A   (Pin 15 on LCD) -> 5V (via 220Ω resistor for backlight)
    - K   (Pin 16 on LCD) -> GND

Run: python3 src/rpi/tests/test_12_lcd.py
"""
import sys
import time

def test_lcd():
    print("=" * 55)
    print("TEST 12: HD44780 16x2 LCD Display (4-bit Mode)")
    print("=" * 55)

    try:
        import RPi.GPIO as GPIO
    except ImportError:
        print("  RPi.GPIO not installed.")
        print("\n  RESULT: FAIL (library not found)")
        return

    # Pin assignments
    RS = 21  # Physical Pin 40
    E  = 22  # Physical Pin 15
    D4 = 23  # Physical Pin 16
    D5 = 24  # Physical Pin 18
    D6 = 25  # Physical Pin 22
    D7 = 26  # Physical Pin 37
    PINS = [RS, E, D4, D5, D6, D7]

    def pulse_enable():
        GPIO.output(E, GPIO.HIGH)
        time.sleep(0.0005)
        GPIO.output(E, GPIO.LOW)
        time.sleep(0.0005)

    def send_nibble(value):
        GPIO.output(D4, (value & 0x01) != 0)
        GPIO.output(D5, (value & 0x02) != 0)
        GPIO.output(D6, (value & 0x04) != 0)
        GPIO.output(D7, (value & 0x08) != 0)
        pulse_enable()

    def send_byte(data, is_char=False):
        GPIO.output(RS, GPIO.HIGH if is_char else GPIO.LOW)
        send_nibble(data >> 4)
        send_nibble(data & 0x0F)
        time.sleep(0.001)

    def write_line(line_num, text):
        addr = 0x80 if line_num == 1 else 0xC0
        send_byte(addr, is_char=False)
        for char in text.ljust(16)[:16]:
            send_byte(ord(char), is_char=True)

    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for p in PINS:
            GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)

        print("  Initializing LCD in 4-bit mode...")
        time.sleep(0.05)  # Wait >40ms after power-on

        # Standard HD44780 reset sequence
        send_nibble(0x03)
        time.sleep(0.005)
        send_nibble(0x03)
        time.sleep(0.001)
        send_nibble(0x03)
        time.sleep(0.001)
        send_nibble(0x02)  # Set 4-bit interface

        # Function set: 4-bit, 2 lines, 5x8 dots
        send_byte(0x28, is_char=False)
        # Display ON, Cursor OFF, Blink OFF
        send_byte(0x0C, is_char=False)
        # Clear display
        send_byte(0x01, is_char=False)
        time.sleep(0.003)
        # Entry mode set: Increment cursor
        send_byte(0x06, is_char=False)

        print("  Writing test messages to screen:")
        print("    Line 1: '  SENTINEL-AI   '")
        print("    Line 2: '  SYSTEM ONLINE '")
        write_line(1, "  SENTINEL-AI   ")
        write_line(2, "  SYSTEM ONLINE ")
        time.sleep(3.0)

        print("  Updating screen to sensor test line...")
        write_line(1, "T: 24.5C H: 50% ")
        write_line(2, "GAS: NORMAL GPS ")
        time.sleep(2.0)

        # Clear display
        send_byte(0x01, is_char=False)
        time.sleep(0.003)
        write_line(1, " TEST COMPLETE  ")
        time.sleep(1.0)

        print("\n  RESULT: PASS (LCD instructions completed)")

    except Exception as e:
        print(f"\n  LCD error: {e}")
        print("\n  RESULT: FAIL")
    finally:
        try:
            for p in PINS:
                GPIO.output(p, GPIO.LOW)
            GPIO.cleanup(PINS)
        except Exception:
            pass

if __name__ == "__main__":
    test_lcd()
