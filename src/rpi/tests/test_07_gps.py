#!/usr/bin/env python3
"""
Test 07: NEO-6M GPS Module via UART
====================================
Tests serial communication with NEO-6M GPS on /dev/serial0 (9600 baud).

Wiring:
    VCC: Pin 1 (3.3V) or Pin 2 (5V if module has onboard 3.3V LDO)
    GND: Pin 6 (GND)
    TX on GPS -> Pin 10 (GPIO 15 / RXD)
    RX on GPS -> Pin 8  (GPIO 14 / TXD)

Prerequisites:
    sudo raspi-config -> Interface Options -> Serial Port
    - Login shell over serial: NO
    - Serial port hardware enabled: YES

Run: python3 src/rpi/tests/test_07_gps.py
"""
import os
import sys
import time

def parse_nmea_lat_lon(lat_str, lat_dir, lon_str, lon_dir):
    """Converts NMEA ddmm.mmmm to decimal degrees."""
    try:
        if not lat_str or not lon_str:
            return None, None
        lat_deg = float(lat_str[:2])
        lat_min = float(lat_str[2:])
        lat = lat_deg + (lat_min / 60.0)
        if lat_dir == 'S':
            lat = -lat

        lon_deg = float(lon_str[:3])
        lon_min = float(lon_str[3:])
        lon = lon_deg + (lon_min / 60.0)
        if lon_dir == 'W':
            lon = -lon
        return lat, lon
    except Exception:
        return None, None

def test_gps():
    print("=" * 55)
    print("TEST 07: NEO-6M GPS Module Check (/dev/serial0)")
    print("=" * 55)

    port_path = "/dev/serial0"
    if not os.path.exists(port_path):
        # Alternative fallback on some Pi setups
        if os.path.exists("/dev/ttyAMA0"):
            port_path = "/dev/ttyAMA0"
        elif os.path.exists("/dev/ttyS0"):
            port_path = "/dev/ttyS0"
        else:
            print("  Serial port /dev/serial0 not found!")
            print("  Ensure UART is enabled in /boot/firmware/config.txt (enable_uart=1)")
            print("\n  RESULT: FAIL (UART unavailable)")
            return

    try:
        import serial
    except ImportError:
        print("  pyserial not installed. Install with: pip install pyserial")
        print("\n  RESULT: FAIL (library not found)")
        return

    print(f"  Opening serial port {port_path} at 9600 baud...")
    try:
        ser = serial.Serial(port_path, baudrate=9600, timeout=2.0)
        print("  Serial port opened successfully.\n")
    except Exception as e:
        print(f"  Failed to open {port_path}: {e}")
        print("\n  RESULT: FAIL (port open error)")
        return

    print("  Listening for NMEA sentences for up to 15 seconds (Ctrl+C to abort)...")
    start_time = time.time()
    sentences_received = 0
    got_fix = False
    latest_lat = None
    latest_lon = None
    satellites = 0

    try:
        while time.time() - start_time < 15.0:
            line = ser.readline().decode("ascii", errors="replace").strip()
            if not line.startswith("$"):
                continue

            sentences_received += 1

            if line.startswith("$GPGGA") or line.startswith("$GNGGA"):
                parts = line.split(",")
                if len(parts) > 7:
                    fix_qual = parts[6]
                    sats = parts[7]
                    satellites = int(sats) if sats.isdigit() else 0
                    if fix_qual in ("1", "2"):
                        got_fix = True
                        lat, lon = parse_nmea_lat_lon(parts[2], parts[3], parts[4], parts[5])
                        if lat and lon:
                            latest_lat, latest_lon = lat, lon

            elif line.startswith("$GPRMC") or line.startswith("$GNRMC"):
                parts = line.split(",")
                if len(parts) > 2 and parts[2] == "A":
                    got_fix = True
                    lat, lon = parse_nmea_lat_lon(parts[3], parts[4], parts[5], parts[6])
                    if lat and lon:
                        latest_lat, latest_lon = lat, lon

            # Print first 5 raw sentences
            if sentences_received <= 5:
                print(f"    Raw [{sentences_received}]: {line[:65]}")

            if got_fix:
                print(f"\n  >>> SATELLITE FIX ACQUIRED! <<<")
                print(f"      Satellites: {satellites}")
                print(f"      Latitude:   {latest_lat:.6f}")
                print(f"      Longitude:  {latest_lon:.6f}")
                break

    except KeyboardInterrupt:
        print("\n  Test aborted by user.")
    finally:
        ser.close()

    if sentences_received == 0:
        print("\n  No data received from GPS!")
        print("  Check wiring: GPS TX -> Pi Pin 10 (RX), GPS RX -> Pi Pin 8 (TX)")
        print("  Check power: GPS VCC -> 3.3V or 5V, GND -> Pin 6")
        print("\n  RESULT: NOT DETECTED")
    elif got_fix:
        print("\n  RESULT: PASS (GPS communication OK with satellite fix)")
    else:
        print(f"\n  Received {sentences_received} NMEA sentences (Status: NO FIX / SEARCHING).")
        print("  GPS hardware is responding properly. Note: Indoors may require 5-15 mins")
        print("  or proximity to a window for satellite lock.")
        print("\n  RESULT: PASS (UART communication verified, searching for satellites)")

if __name__ == "__main__":
    test_gps()
