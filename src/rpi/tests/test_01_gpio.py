#!/usr/bin/env python3
"""
Test 01: GPIO Library Availability
===================================
Checks that RPi.GPIO is installed and BCM mode can be set.
Does NOT change pin states.

Run: python3 src/rpi/tests/test_01_gpio.py
"""
import sys

def test_gpio():
    print("=" * 50)
    print("TEST 01: GPIO Library Check")
    print("=" * 50)

    try:
        import RPi.GPIO as GPIO
        print(f"  RPi.GPIO version: {GPIO.VERSION}")
        print(f"  Board revision:   {GPIO.RPI_INFO}")
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        print("  BCM mode set:     OK")
        GPIO.cleanup()
        print("\n  RESULT: PASS")
    except ImportError:
        print("  RPi.GPIO not installed.")
        print("  Install with: pip install RPi.GPIO")
        print("\n  RESULT: FAIL (library not found)")
    except RuntimeError as e:
        print(f"  GPIO RuntimeError: {e}")
        print("  This may happen if not running on a Raspberry Pi.")
        print("\n  RESULT: WARNING (not a Raspberry Pi)")
    except Exception as e:
        print(f"  Unexpected error: {e}")
        print("\n  RESULT: FAIL")

if __name__ == "__main__":
    test_gpio()