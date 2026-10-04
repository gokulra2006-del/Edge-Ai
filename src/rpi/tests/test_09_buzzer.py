#!/usr/bin/env python3
"""
Test 09: Active Buzzer Alert
=============================
Tests active buzzer beep patterns on GPIO 16 (Pin 36).

Wiring:
    - Buzzer (+) / Signal: GPIO 16 (Pin 36)
    - Buzzer (-):         GND (Pin 34)

Note: For active buzzer, HIGH activates tone and LOW deactivates tone.

Run: python3 src/rpi/tests/test_09_buzzer.py
"""
import sys
import time

def test_buzzer():
    print("=" * 50)
    print("TEST 09: Active Buzzer Sound Test")
    print("=" * 50)
    print("  Target Pin: BCM GPIO 16 (Physical Pin 36)")

    try:
        import RPi.GPIO as GPIO
    except ImportError:
        print("  RPi.GPIO not installed.")
        print("\n  RESULT: FAIL (library not found)")
        return

    BUZZER_PIN = 16

    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(BUZZER_PIN, GPIO.OUT, initial=GPIO.LOW)

        print("  1. Playing 3 short alarm beeps (100ms)...")
        for i in range(3):
            GPIO.output(BUZZER_PIN, GPIO.HIGH)
            time.sleep(0.1)
            GPIO.output(BUZZER_PIN, GPIO.LOW)
            time.sleep(0.1)

        time.sleep(0.5)

        print("  2. Playing 1 long alert tone (500ms)...")
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        time.sleep(0.5)
        GPIO.output(BUZZER_PIN, GPIO.LOW)

        print("\n  RESULT: PASS (Buzzer pulses triggered)")

    except Exception as e:
        print(f"\n  Buzzer GPIO error: {e}")
        print("\n  RESULT: FAIL")
    finally:
        try:
            GPIO.output(BUZZER_PIN, GPIO.LOW)
            GPIO.cleanup(BUZZER_PIN)
        except Exception:
            pass

if __name__ == "__main__":
    test_buzzer()
