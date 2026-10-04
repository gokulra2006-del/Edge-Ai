#!/usr/bin/env python3
"""
Test 02: I2C Bus Scan
======================
Scans /dev/i2c-1 for all connected devices.
Reports detected addresses and identifies known devices.

Expected devices (may not all be present):
    0x68 = MPU-6050 (Accelerometer/Gyroscope on GY-87)
    0x1E = HMC5883L (Magnetometer on GY-87)
    0x0D = QMC5883L (Alternative Magnetometer on some GY-87 boards)
    0x77 = BMP180 (Barometric Pressure on GY-87)
    0x48 = ADS1115 (16-bit ADC for MQ-2 gas sensor)

Run: python3 src/rpi/tests/test_02_i2c_scan.py
Equivalent to: sudo i2cdetect -y 1
"""
import os
import sys

def test_i2c_scan():
    print("=" * 50)
    print("TEST 02: I2C Bus Scan")
    print("=" * 50)

    if not os.path.exists("/dev/i2c-1"):
        print("  /dev/i2c-1 not found!")
        print("  Enable I2C with: sudo raspi-config -> Interface Options -> I2C -> Enable")
        print("\n  RESULT: FAIL (I2C not enabled)")
        return

    try:
        import smbus2
        bus = smbus2.SMBus(1)
        print("  I2C bus /dev/i2c-1 opened successfully.\n")
    except ImportError:
        print("  smbus2 not installed. Install with: pip install smbus2")
        print("\n  RESULT: FAIL (library not found)")
        return
    except Exception as e:
        print(f"  Could not open I2C bus: {e}")
        print("\n  RESULT: FAIL")
        return

    known = {
        0x68: "MPU-6050 (Accel/Gyro on GY-87)",
        0x1E: "HMC5883L (Magnetometer on GY-87)",
        0x0D: "QMC5883L (Alt. Magnetometer on GY-87)",
        0x77: "BMP180 (Barometer on GY-87)",
        0x48: "ADS1115 (16-bit ADC for MQ-2)",
    }

    found = []
    for addr in range(0x03, 0x78):
        try:
            bus.read_byte(addr)
            found.append(addr)
        except Exception:
            pass

    bus.close()

    if found:
        print(f"  Found {len(found)} device(s):\n")
        for addr in found:
            name = known.get(addr, "Unknown device")
            print(f"    {hex(addr)} ({addr}) = {name}")
        print(f"\n  RESULT: PASS ({len(found)} device(s) detected)")
    else:
        print("  No I2C devices found!")
        print("  Check wiring: SDA = Pin 3, SCL = Pin 5")
        print("  Check power: GY-87 VCC = Pin 1 (3.3V), GND = Pin 6")
        print("\n  RESULT: NOT DETECTED")

if __name__ == "__main__":
    test_i2c_scan()
