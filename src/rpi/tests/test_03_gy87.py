#!/usr/bin/env python3
"""
Test 03: GY-87 IMU Detection & Reading
========================================
Detects GY-87 sub-sensors on I2C and reads live accelerometer data.

Expected: MPU-6050 at 0x68 (always present on GY-87)
Optional: HMC5883L at 0x1E or QMC5883L at 0x0D (magnetometer)
Optional: BMP180 at 0x77 (barometric pressure)

Run: python3 src/rpi/tests/test_03_gy87.py
"""
import os
import sys
import time

def test_gy87():
    print("=" * 50)
    print("TEST 03: GY-87 IMU Board Detection")
    print("=" * 50)

    if not os.path.exists("/dev/i2c-1"):
        print("  I2C bus not available.")
        print("\n  RESULT: FAIL")
        return

    try:
        import smbus2
        bus = smbus2.SMBus(1)
    except ImportError:
        print("  smbus2 not installed.")
        print("\n  RESULT: FAIL")
        return

    # Check MPU-6050 (core accelerometer/gyroscope)
    mpu_found = False
    try:
        bus.read_byte(0x68)
        who_am_i = bus.read_byte_data(0x68, 0x75)
        print(f"  MPU-6050 detected at 0x68 (WHO_AM_I = {hex(who_am_i)})")
        mpu_found = True
    except Exception:
        print("  MPU-6050 NOT detected at 0x68")
        print("  Check wiring: SDA=Pin 3, SCL=Pin 5, VCC=Pin 1, GND=Pin 6")
        print("\n  RESULT: NOT DETECTED")
        bus.close()
        return

    # Wake up MPU-6050
    try:
        bus.write_byte_data(0x68, 0x6B, 0x00)
        time.sleep(0.1)
        print("  MPU-6050 woken up (power management register cleared)")
    except Exception as e:
        print(f"  Wake-up error: {e}")

    # Enable bypass mode to access magnetometer/barometer directly
    try:
        bus.write_byte_data(0x68, 0x37, 0x02)
        time.sleep(0.1)
        print("  MPU-6050 I2C bypass mode enabled")
    except Exception as e:
        print(f"  Bypass mode error: {e}")

    # Check for magnetometer
    mag_found = False
    for addr, name in [(0x1E, "HMC5883L"), (0x0D, "QMC5883L")]:
        try:
            bus.read_byte(addr)
            print(f"  {name} magnetometer detected at {hex(addr)}")
            mag_found = True
            break
        except Exception:
            pass
    if not mag_found:
        print("  Magnetometer not detected (HMC5883L/QMC5883L)")

    # Check for barometer
    baro_found = False
    try:
        bus.read_byte(0x77)
        print("  BMP180 barometer detected at 0x77")
        baro_found = True
    except Exception:
        print("  BMP180 barometer not detected at 0x77")

    # Read live accelerometer data
    print("\n  Live Accelerometer Readings (5 samples):")
    for i in range(5):
        try:
            data = bus.read_i2c_block_data(0x68, 0x3B, 6)
            raw_x = (data[0] << 8) | data[1]
            raw_y = (data[2] << 8) | data[3]
            raw_z = (data[4] << 8) | data[5]
            ax = (raw_x - 65536 if raw_x > 32767 else raw_x) / 16384.0
            ay = (raw_y - 65536 if raw_y > 32767 else raw_y) / 16384.0
            az = (raw_z - 65536 if raw_z > 32767 else raw_z) / 16384.0
            print(f"    [{i+1}] X={ax:+.3f}g  Y={ay:+.3f}g  Z={az:+.3f}g")
        except Exception as e:
            print(f"    [{i+1}] Read error: {e}")
        time.sleep(0.2)

    bus.close()

    sensors = ["MPU-6050"]
    if mag_found:
        sensors.append("Magnetometer")
    if baro_found:
        sensors.append("BMP180")
    print(f"\n  RESULT: PASS ({', '.join(sensors)} detected)")

if __name__ == "__main__":
    test_gy87()
