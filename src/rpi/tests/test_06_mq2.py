#!/usr/bin/env python3
"""
Test 06: MQ-2 Gas & Smoke Sensor via ADS1115 ADC
=================================================
Reads analog gas concentration output from MQ-2 sensor via ADS1115 channel A0.

Hardware Setup:
    - MQ-2 VCC: Pin 2 (5V) - Heater requires 5V
    - MQ-2 GND: Pin 6 (GND)
    - MQ-2 AOUT: Connected to voltage divider (10k resistor to A0, 20k resistor to GND)
                 Ratio = (10k + 20k) / 20k = 1.5x reduction so max 5V -> 3.33V (safe for ADS1115).
    - ADS1115 A0: Input from voltage divider midpoint.

Note:
    Output is labeled as "Relative Gas Level" (NOT calibrated PPM).
    MQ-2 requires 20-30 seconds minimum warm-up time after power-on.

Run: python3 src/rpi/tests/test_06_mq2.py
"""
import os
import sys
import time

def test_mq2():
    print("=" * 55)
    print("TEST 06: MQ-2 Gas & Smoke Reading (via ADS1115 A0)")
    print("=" * 55)

    if not os.path.exists("/dev/i2c-1"):
        print("  I2C bus /dev/i2c-1 not available.")
        print("\n  RESULT: FAIL (I2C disabled)")
        return

    try:
        import smbus2
        bus = smbus2.SMBus(1)
    except ImportError:
        print("  smbus2 not installed. Install with: pip install smbus2")
        print("\n  RESULT: FAIL (library not found)")
        return

    # Check ADS1115 at 0x48
    try:
        bus.read_byte(0x48)
        print("  ADS1115 detected at 0x48")
    except Exception:
        print("  ADS1115 NOT detected at 0x48.")
        print("  Check ADS1115 wiring: VDD=Pin 1, GND=Pin 6, SDA=Pin 3, SCL=Pin 5")
        print("\n  RESULT: NOT DETECTED")
        bus.close()
        return

    print("  Voltage divider ratio configured: 1.5x (10k / 20k divider)")
    print("  Note: Gas level is relative intensity (0-1000 scale), NOT calibrated PPM.\n")
    print("  Sampling MQ-2 on AIN0 (10 samples, 1 sec interval):")

    readings = []
    for i in range(10):
        try:
            # Config: Single-shot, AIN0 vs GND, PGA +/-4.096V, 128 SPS
            config = 0xC183
            bus.write_i2c_block_data(0x48, 0x01, [(config >> 8) & 0xFF, config & 0xFF])
            time.sleep(0.02)
            result = bus.read_i2c_block_data(0x48, 0x00, 2)
            raw = (result[0] << 8) | result[1]
            if raw > 32767:
                raw -= 65536

            # Calculate voltages
            v_adc = (raw / 32768.0) * 4.096
            v_sensor = v_adc * 1.5  # Reconstruct 0-5V sensor output
            # Relative intensity index (0 to 1000 scale based on 0-5V range)
            relative_level = max(0.0, min(1000.0, (v_sensor / 5.0) * 1000.0))

            readings.append(v_sensor)
            print(
                f"    [{i+1:2d}] ADC Raw: {raw:6d} | ADC Volt: {v_adc:.3f}V | "
                f"Sensor Volt: {v_sensor:.3f}V | Rel Level: {relative_level:5.1f} / 1000"
            )
        except Exception as e:
            print(f"    [{i+1:2d}] Read error: {e}")

        time.sleep(1.0)

    bus.close()

    if readings:
        avg_v = sum(readings) / len(readings)
        print(f"\n  Average Sensor Voltage: {avg_v:.3f}V")
        if avg_v > 0.05:
            print("  Signal detected: MQ-2 sensor active.")
            print("\n  RESULT: PASS")
        else:
            print("  Warning: Near-zero voltage detected. Check MQ-2 VCC (5V) & ground connections.")
            print("\n  RESULT: WARNING (low voltage)")
    else:
        print("\n  RESULT: FAIL (no readings)")

if __name__ == "__main__":
    test_mq2()
