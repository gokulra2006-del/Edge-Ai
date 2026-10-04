#!/usr/bin/env python3
"""
Test 08: LED Indicators (Traffic Light Status)
==============================================
Tests the three status LED indicators in sequence and all together.

Wiring (with 220Ω-330Ω current limiting resistor in series with each):
    - RED LED:    Anode (+) to GPIO 5  (Pin 29), Cathode (-) to GND (Pin 30)
    - YELLOW LED: Anode (+) to GPIO 6  (Pin 31), Cathode (-) to GND (Pin 34)
    - GREEN LED:  Anode (+) to GPIO 13 (Pin 33), Cathode (-) to GND (Pin 39)

Run: python3 src/rpi/tests/test_08_leds.py
"""
import sys
import time

def test_leds():
    print("=" * 50)
    print("TEST 08: LED Status Indicators")
    print("=" * 50)

    try:
        import RPi.GPIO as GPIO
    except ImportError:
        print("  RPi.GPIO not installed.")
        print("\n  RESULT: FAIL (library not found)")
        return

    RED_PIN = 5     # Physical Pin 29
    YELLOW_PIN = 6  # Physical Pin 31
    GREEN_PIN = 13  # Physical Pin 33
    PINS = [RED_PIN, YELLOW_PIN, GREEN_PIN]

    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        for p in PINS:
            GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)

        print("  1. Testing RED LED (GPIO 5 / Pin 29)...")
        GPIO.output(RED_PIN, GPIO.HIGH)
        time.sleep(1.0)
        GPIO.output(RED_PIN, GPIO.LOW)
        time.sleep(0.3)

        print("  2. Testing YELLOW LED (GPIO 6 / Pin 31)...")
        GPIO.output(YELLOW_PIN, GPIO.HIGH)
        time.sleep(1.0)
        GPIO.output(YELLOW_PIN, GPIO.LOW)
        time.sleep(0.3)

        print("  3. Testing GREEN LED (GPIO 13 / Pin 33)...")
        GPIO.output(GREEN_PIN, GPIO.HIGH)
        time.sleep(1.0)
        GPIO.output(GREEN_PIN, GPIO.LOW)
        time.sleep(0.3)

        print("  4. Testing ALL LEDs simultaneous ON...")
        for p in PINS:
            GPIO.output(p, GPIO.HIGH)
        time.sleep(1.0)
        for p in PINS:
            GPIO.output(p, GPIO.LOW)

        print("\n  RESULT: PASS (All LED GPIOs toggled successfully)")

    except Exception as e:
        print(f"\n  GPIO Error during LED test: {e}")
        print("\n  RESULT: FAIL")
    finally:
        try:
            for p in PINS:
                GPIO.output(p, GPIO.LOW)
            GPIO.cleanup(PINS)
        except Exception:
            pass

if __name__ == "__main__":
    test_leds()
