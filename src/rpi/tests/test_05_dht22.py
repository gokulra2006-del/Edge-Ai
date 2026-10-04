#!/usr/bin/env python3
"""
Test 05: DHT22 Temperature & Humidity Sensor
=============================================
Reads live temperature and relative humidity from DHT22 on GPIO 4.

Wiring:
    VCC:  Pin 1 (3.3V) or Pin 2 (5V if 5V tolerant module)
    GND:  Pin 9 or Pin 6
    DATA: GPIO 4 (Pin 7) with 4.7k-10k pull-up resistor to VCC

Run: python3 src/rpi/tests/test_05_dht22.py
"""
import sys
import time

def test_dht22():
    print("=" * 50)
    print("TEST 05: DHT22 Temperature & Humidity Reading")
    print("=" * 50)
    print("  Target Pin: BCM GPIO 4 (Physical Pin 7)")

    sensor_device = None
    read_method = None

    # Try adafruit_dht (recommended on modern Raspberry Pi OS)
    try:
        import board
        import adafruit_dht
        sensor_device = adafruit_dht.DHT22(board.D4)
        read_method = "adafruit_dht"
        print("  Driver: adafruit_dht initialized successfully.")
    except (ImportError, NotImplementedError):
        # Fallback to Adafruit_DHT legacy or mock
        try:
            import Adafruit_DHT
            sensor_device = Adafruit_DHT.DHT22
            read_method = "legacy"
            print("  Driver: Adafruit_DHT (legacy) initialized.")
        except ImportError:
            print("  DHT22 libraries not installed.")
            print("  Install with: pip install adafruit-circuitpython-dht")
            print("  System dependency: sudo apt-get install libgpiod2")
            print("\n  RESULT: FAIL (driver library missing)")
            return

    print("\n  Collecting 5 samples (sampling rate is 0.5 Hz / 2 sec interval):")
    valid_reads = 0

    for i in range(5):
        temp_c = None
        humidity = None

        try:
            if read_method == "adafruit_dht":
                temp_c = sensor_device.temperature
                humidity = sensor_device.humidity
            elif read_method == "legacy":
                import Adafruit_DHT
                humidity, temp_c = Adafruit_DHT.read_retry(sensor_device, 4)
        except RuntimeError as e:
            # DHT sensors frequently have minor timing checksum errors on Linux
            print(f"    [{i+1}] Read retry ({e})")
            time.sleep(2.0)
            continue
        except Exception as e:
            print(f"    [{i+1}] Exception: {e}")
            time.sleep(2.0)
            continue

        if temp_c is not None and humidity is not None:
            # Sanity check ranges
            if -40.0 <= temp_c <= 80.0 and 0.0 <= humidity <= 100.0:
                print(f"    [{i+1}] Temperature: {temp_c:5.1f} C   Humidity: {humidity:5.1f} %  [VALID]")
                valid_reads += 1
            else:
                print(f"    [{i+1}] Out of range: Temp={temp_c}C, Hum={humidity}% [INVALID]")
        else:
            print(f"    [{i+1}] No data returned.")

        if i < 4:
            time.sleep(2.0)

    if sensor_device and hasattr(sensor_device, "exit"):
        try:
            sensor_device.exit()
        except Exception:
            pass

    if valid_reads > 0:
        print(f"\n  RESULT: PASS ({valid_reads}/5 valid readings obtained)")
    else:
        print("\n  RESULT: NOT DETECTED (no valid readings)")
        print("  Check wiring: VCC=Pin 1, DATA=Pin 7 (GPIO 4), GND=Pin 9")
        print("  Ensure a 4.7k-10k pull-up resistor is present between VCC and DATA")

if __name__ == "__main__":
    test_dht22()
