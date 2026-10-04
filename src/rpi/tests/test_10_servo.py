#!/usr/bin/env python3
"""
Test 10: SG90 Micro Servo Barrier/Actuator
==========================================
Tests PWM angle control on GPIO 12 (Physical Pin 32, PWM0).

Wiring:
    - Brown / Black wire: GND (Pin 14)
    - Red wire:           5V  (Pin 2 or Pin 4)
    - Orange/Yellow wire: GPIO 12 (Pin 32, PWM0)

PWM Parameters:
    - Frequency: 50 Hz (20ms cycle)
    - 0 degrees:   ~2.5% duty cycle (0.5ms pulse)
    - 90 degrees:  ~7.5% duty cycle (1.5ms pulse) - Neutral
    - 180 degrees: ~12.5% duty cycle (2.5ms pulse)

Run: python3 src/rpi/tests/test_10_servo.py
"""
import sys
import time

def angle_to_duty(angle_deg: float) -> float:
    """Converts 0-180 degree angle to 50Hz PWM duty cycle percentage."""
    angle_deg = max(0.0, min(180.0, angle_deg))
    return 2.5 + (angle_deg / 180.0) * 10.0

def test_servo():
    print("=" * 50)
    print("TEST 10: SG90 Micro Servo Actuator")
    print("=" * 50)
    print("  Target Pin: BCM GPIO 12 (Physical Pin 32, PWM0)")

    try:
        import RPi.GPIO as GPIO
    except ImportError:
        print("  RPi.GPIO not installed.")
        print("\n  RESULT: FAIL (library not found)")
        return

    SERVO_PIN = 12

    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(SERVO_PIN, GPIO.OUT)

        pwm = GPIO.PWM(SERVO_PIN, 50)  # 50 Hz
        pwm.start(angle_to_duty(90))   # Start at neutral 90 deg
        time.sleep(0.5)

        print("  1. Moving to Neutral position (90 deg)...")
        pwm.ChangeDutyCycle(angle_to_duty(90))
        time.sleep(1.0)

        print("  2. Moving to 0 deg (Open / Min)...")
        pwm.ChangeDutyCycle(angle_to_duty(0))
        time.sleep(1.0)

        print("  3. Moving to 180 deg (Closed / Max)...")
        pwm.ChangeDutyCycle(angle_to_duty(180))
        time.sleep(1.0)

        print("  4. Returning to Neutral (90 deg)...")
        pwm.ChangeDutyCycle(angle_to_duty(90))
        time.sleep(1.0)

        # Allow mechanical settling then release PWM signal to prevent jitter/heating
        pwm.ChangeDutyCycle(0)
        time.sleep(0.2)
        pwm.stop()

        print("\n  RESULT: PASS (Servo sweep completed)")

    except Exception as e:
        print(f"\n  Servo PWM error: {e}")
        print("\n  RESULT: FAIL")
    finally:
        try:
            GPIO.cleanup(SERVO_PIN)
        except Exception:
            pass

if __name__ == "__main__":
    test_servo()
