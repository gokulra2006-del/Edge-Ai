#!/usr/bin/env python3
"""
Test 04: ADS1115 ADC Detection & Raw Reading
==============================================
Detects ADS1115 at I2C address 0x48 and reads raw ADC value + voltage.

Connection: VDD=Pin 1 (3.3V), GND=Pin 6, SDA=Pin 3, SCL=Pin 5
MQ-2 sensor is connected to A0 through a voltage divider.

Run: python3 src/rpi/tests/test_04_ads1115.py
"""
import os
import sys
import time

def test_ads1115():
    print("=" * 50)
    print("TEST 04: ADS1115 16-bit ADC Detection")
    print("=" * 50)

    if not os.path.exists("/dev/i2c-1"):
        print("  I2C not available.")
        print("\n  RESULT: FAIL")
        return

    try:
        import smbus2
        bus = smbus2.SMBus(1)
    except ImportError:
        print("  smbus2 not installed.")
        print("\n  RESULT: FAIL")
        return

    try:
        bus.read_byte(0x48)
        print("  ADS1115 detected at 0x48")
    except Exception:
        print("  ADS1115 NOT detected at 0x48")
        print("  Check wiring: VDD=Pin 1, GND=Pin 6, SDA=Pin 3, SCL=Pin 5")
        print("  Check ADDR pin: Leave unconnected or tie to GND for 0x48")
        print("\n  RESULT: NOT DETECTED")
        bus.close()
        return

    # Read AIN0 (where MQ-2 voltage divider output is connected)
    print("\n  Reading AIN0 (MQ-2 connection), 5 samples:")
    for i in range(5):
        try:
            # Config: OS=start, MUX=AIN0-GND, PGA=4.096V, single-shot, 128SPS
            config = 0xC183
            bus.write_i2c_block_data(0x48, 0x01, [(config >> 8) & 0xFF, config & 0xFF])
            time.sleep(0.01)
            result = bus.read_i2c_block_data(0x48, 0x00, 2)
            raw = (result[0] << 8) | result[1]
            if raw > 32767:
                raw -= 65536
            voltage = (raw / 32768.0) * 4.096
            print(f"    [{i+1}] Raw ADC: {raw:6d}  Voltage: {voltage:.4f}V")
        except Exception as e:
            print(f"    [{i+1}] Read error: {e}")
        time.sleep(0.2)

    bus.close()
    print("\n  RESULT: PASS (ADS1115 responding at 0x48)")

if __name__ == "__main__":
    test_ads1115()
