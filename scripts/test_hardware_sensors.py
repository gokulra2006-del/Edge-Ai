"""
SENTINEL-AI: Raspberry Pi Hardware Sensor & Actuator Diagnostic Tool.
====================================================================
Run this script directly on your Raspberry Pi to test each individual
sensor and actuator before launching the full AI emergency node.

Usage:
    python3 scripts/test_hardware_sensors.py
"""
import math
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.modules.sensors.gpio_registry import GPIO_REGISTRY


def print_banner(title: str):
    print("\n" + "=" * 65)
    print(f"  {title.upper()}")
    print("=" * 65)


def check_system():
    print_banner("1. System Environment Check")
    is_rpi = False
    model_name = "Unknown System"
    if os.path.exists("/proc/device-tree/model"):
        try:
            with open("/proc/device-tree/model", "r") as f:
                model_name = f.read().strip("\x00").strip()
                is_rpi = "Raspberry Pi" in model_name
        except Exception:
            pass

    import platform
    print(f"  [HOST] Architecture : {platform.system()} {platform.machine()}")
    print(f"  [HOST] Model        : {model_name}")
    print(f"  [HOST] Is Pi Device : {is_rpi}")

    i2c_dev = os.path.exists("/dev/i2c-1")
    print(f"  [I2C]  /dev/i2c-1   : {'DETECTED' if i2c_dev else 'NOT FOUND (Enable via raspi-config)'}")

    cam_dev = os.path.exists("/dev/video0")
    print(f"  [CAM]  /dev/video0  : {'DETECTED' if cam_dev else 'NO USB/CSI CAMERA DETECTED'}")

    return is_rpi


def test_i2c_bus():
    print_banner("2. I2C Bus Scan (MPU-6050 & ADS1115)")
    try:
        import smbus2
        bus = smbus2.SMBus(1)
        found = []
        for addr in range(0x03, 0x78):
            try:
                bus.read_byte(addr)
                found.append(hex(addr))
            except Exception:
                pass
        bus.close()
        print(f"  Active I2C Addresses Found: {found}")

        if "0x68" in found:
            print("  -> MPU-6050 IMU Accelerometer: DETECTED (0x68) [OK]")
        else:
            print("  -> MPU-6050 IMU: NOT FOUND at 0x68 (Check SDA/SCL wiring)")

        if "0x48" in found:
            print("  -> ADS1115 ADC (MQ-2 Gas Sensor): DETECTED (0x48) [OK]")
        else:
            print("  -> ADS1115 ADC: NOT FOUND at 0x48 (Check wiring if using ADC)")

    except ImportError:
        print("  [WARNING] smbus2 library not installed. Install with: pip install smbus2")
    except Exception as e:
        print(f"  [ERROR] I2C Scan failed: {e}")


def test_mpu6050(duration_sec=3):
    print_banner("3. MPU-6050 Live Telemetry Test (Crash / Impact IMU)")
    try:
        import smbus2
        bus = smbus2.SMBus(1)
        # Wake up MPU-6050 (PWR_MGMT_1 register 0x6B = 0)
        bus.write_byte_data(0x68, 0x6B, 0x00)
        time.sleep(0.05)

        print(f"  Reading live acceleration for {duration_sec} seconds (Shake sensor to see G-force changes):")
        end_time = time.time() + duration_sec
        while time.time() < end_time:
            data = bus.read_i2c_block_data(0x68, 0x3B, 6)
            rx = (data[0] << 8) | data[1]
            ry = (data[2] << 8) | data[3]
            rz = (data[4] << 8) | data[5]

            ax = (rx - 65536 if rx > 32767 else rx) / 16384.0
            ay = (ry - 65536 if ry > 32767 else ry) / 16384.0
            az = (rz - 65536 if rz > 32767 else rz) / 16384.0
            composite = math.sqrt(ax**2 + ay**2 + az**2) - 1.0

            impact_flag = ">> IMPACT / CRASH DETECTED <<" if composite > 2.5 else "NOMINAL"
            print(f"    Accel X={ax:+.2f}g | Y={ay:+.2f}g | Z={az:+.2f}g | Net G={max(0.0, composite):.2f}g | {impact_flag}")
            time.sleep(0.3)
        bus.close()
        print("  [OK] MPU-6050 is functioning properly.")
    except Exception as e:
        print(f"  [NOTICE] Could not read physical MPU-6050: {e}")


def test_mq2_gas():
    print_banner("4. MQ-2 Smoke & Flammable Gas Sensor Test")
    # Option A: via ADS1115 (Analog)
    read_ok = False
    try:
        import smbus2
        bus = smbus2.SMBus(1)
        # Single-shot conversion AIN0
        bus.write_i2c_block_data(0x48, 0x01, [0xC1, 0x83])
        time.sleep(0.02)
        res = bus.read_i2c_block_data(0x48, 0x00, 2)
        raw_adc = (res[0] << 8) | res[1]
        voltage = (raw_adc * 4.096) / 32768.0
        smoke_ppm = max(5.0, voltage * 80.0)
        print(f"  [ADC ADS1115] AIN0 Voltage: {voltage:.3f} V | Estimated Smoke: {smoke_ppm:.1f} PPM")
        bus.close()
        read_ok = True
    except Exception:
        pass

    # Option B: via Digital Out (GPIO)
    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        pin_d = 17  # Optional digital pin for MQ-2 DO
        GPIO.setup(pin_d, GPIO.IN)
        val = GPIO.input(pin_d)
        print(f"  [Digital Pin BCM {pin_d}] MQ-2 DO State: {'HAZARD (HIGH)' if val else 'CLEAR (LOW)'}")
        read_ok = True
    except Exception:
        pass

    if not read_ok:
        print("  [NOTICE] MQ-2 reading skipped. Connect MQ-2 to ADS1115 AIN0 or GPIO 17.")


def test_dht22():
    print_banner("5. DHT-22 / DHT-11 Temperature & Humidity Sensor Test")
    try:
        import adafruit_dht
        import board
        dht = adafruit_dht.DHT22(board.D4)
        temp_c = dht.temperature
        humidity = dht.humidity
        print(f"  [DHT-22] Temperature: {temp_c:.1f} °C | Humidity: {humidity:.1f} % [OK]")
    except ImportError:
        print("  [NOTICE] adafruit-circuitpython-dht library not installed.")
        print("  Install with: pip install adafruit-circuitpython-dht")
    except Exception as e:
        print(f"  [NOTICE] DHT-22 read note: {e} (DHT sensors require 1-2s between reads)")


def test_camera():
    print_banner("6. Camera Capture Test (/dev/video0 / CSI)")
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("  [WARNING] OpenCV could not open /dev/video0.")
            return

        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None:
            h, w, c = frame.shape
            out_path = BASE_DIR / "data" / "recordings" / "test_camera.jpg"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out_path), frame)
            print(f"  [OK] Successfully captured test frame ({w}x{h} px, {c} channels).")
            print(f"  Saved snapshot to: {out_path}")
        else:
            print("  [ERROR] Camera opened but frame grab failed.")
    except ImportError:
        print("  [NOTICE] opencv-python not installed. Install with: pip install opencv-python-headless")
    except Exception as e:
        print(f"  [ERROR] Camera test error: {e}")


def test_microphone():
    print_banner("7. USB Microphone Audio Test (ALSA / Siren Classifier)")
    try:
        import pyaudio
        import numpy as np
        p = pyaudio.PyAudio()
        info = p.get_default_input_device_info()
        print(f"  Default Audio Input: {info.get('name')}")

        stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
        print("  Listening for 1.5 seconds...")
        frames = []
        for _ in range(0, int(16000 / 1024 * 1.5)):
            data = stream.read(1024, exception_on_overflow=False)
            frames.append(np.frombuffer(data, dtype=np.int16))
        stream.stop_stream()
        stream.close()
        p.terminate()

        audio_data = np.concatenate(frames)
        rms = np.sqrt(np.mean(audio_data.astype(np.float32)**2))
        db = 20 * math.log10(max(1.0, rms))
        print(f"  [OK] Audio recorded successfully. RMS Amplitude: {rms:.1f} (~{db:.1f} dB)")
    except ImportError:
        print("  [NOTICE] pyaudio not installed. Install with: sudo apt install portaudio19-dev && pip install pyaudio")
    except Exception as e:
        print(f"  [NOTICE] Microphone test note: {e}")


def test_actuators():
    print_banner("8. GPIO Actuators Test (Traffic LEDs, Servo Barrier, Siren Buzzer)")
    try:
        from src.modules.sensors.gpio_actuator import GPIO_ACTUATOR
        if not GPIO_ACTUATOR.is_hardware_active:
            print("  [NOTICE] Physical GPIO not active (RPi.GPIO not found or running on host).")
            return

        print("  [1/4] Testing Traffic Light: RED (Accident Halt)...")
        GPIO_ACTUATOR.set_traffic_light("RED")
        time.sleep(1.0)

        print("  [2/4] Testing Traffic Light: YELLOW (Warning Near-Miss)...")
        GPIO_ACTUATOR.set_traffic_light("YELLOW")
        time.sleep(1.0)

        print("  [3/4] Testing Traffic Light: GREEN (Normal Corridor)...")
        GPIO_ACTUATOR.set_traffic_light("GREEN")
        time.sleep(1.0)

        print("  [4/4] Testing Siren Buzzer (Short 200ms Beep)...")
        GPIO_ACTUATOR.set_buzzer(True)
        time.sleep(0.2)
        GPIO_ACTUATOR.set_buzzer(False)

        print("  [5/5] Testing SG90 Access Barrier Servo...")
        print("    -> Lowering Barrier (CLOSED / 0°)...")
        GPIO_ACTUATOR.set_barrier("CLOSED")
        time.sleep(1.0)
        print("    -> Raising Barrier (OPEN / 90°)...")
        GPIO_ACTUATOR.set_barrier("OPEN")
        time.sleep(1.0)

        print("  [OK] All physical actuators tested successfully!")
    except Exception as e:
        print(f"  [ERROR] Actuator test error: {e}")


def main():
    print("=" * 65)
    print("  SENTINEL-AI EDGE INTELLIGENCE: RASPBERRY PI HARDWARE CHECK  ")
    print("=" * 65)

    check_system()
    test_i2c_bus()
    test_mpu6050()
    test_mq2_gas()
    test_dht22()
    test_camera()
    test_microphone()
    test_actuators()

    print_banner("Diagnostic Complete")
    print("  Ready to run live physical hardware node:")
    print("  $ python3 scripts/run_rpi_node.py\n")


if __name__ == "__main__":
    main()
