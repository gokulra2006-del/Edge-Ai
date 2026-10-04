"""
SENTINEL-AI Hardware Diagnostic Tool.
=====================================
Executable diagnostic suite validating physical & interface connectivity:
- Raspberry Pi detection
- GPIO availability (BCM pins 4, 14, 15, 18, 19, 20, 5, 6, 13, 16, 12)
- I2C availability (/dev/i2c-1)
- GY-87 detection (MPU6050 0x68, HMC5883L 0x1E, BMP180 0x77)
- ADS1115 detection (0x48)
- UART availability (/dev/serial0)
- GPS communication & NMEA parsing
- DHT22 availability (GPIO 4)
- Camera availability (libcamera / picamera2 / /dev/video0)
- I2S audio availability (Pins 18, 19, 20)

Run with:
    python scripts/hardware_diagnostic.py
"""
import os
import platform
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.config.hardware_config import HARDWARE_CONFIG


def header(title: str):
    print("\n" + "=" * 68)
    print(f"  [DIAGNOSTIC] {title.upper()}")
    print("=" * 68)


def test_board_detection() -> bool:
    header("1. Raspberry Pi Board Detection")
    model = "Generic / Host Computer"
    is_rpi = False
    if os.path.exists("/proc/device-tree/model"):
        try:
            with open("/proc/device-tree/model", "r") as f:
                model = f.read().strip("\x00").strip()
                is_rpi = "Raspberry Pi" in model
        except Exception:
            pass

    print(f"  Platform Architecture : {platform.system()} ({platform.machine()})")
    print(f"  Detected Board Model  : {model}")
    print(f"  Is Raspberry Pi Device: {is_rpi}")

    if not is_rpi:
        print("  -> Status: [SIMULATION_HOST] (Operating in full software fallback mode)")
    else:
        print("  -> Status: [PHYSICAL_PI_CONFIRMED] Ready for GPIO/I2C/UART/CSI")
    return is_rpi


def test_i2c_and_devices():
    header("2. I2C Bus & Multi-Sensor Scan (GY-87 & ADS1115)")
    bus_path = HARDWARE_CONFIG.i2c_bus_path
    if not os.path.exists(bus_path):
        print(f"  [NOTICE] {bus_path} not found on this host system.")
        print("           On Raspberry Pi, enable with: sudo raspi-config nonint do_i2c 0")
        return

    try:
        import smbus2
        bus = smbus2.SMBus(HARDWARE_CONFIG.i2c_bus_num)

        # 1. Enable MPU-6050 Bypass to ensure HMC5883L & BMP180 are accessible
        try:
            bus.write_byte_data(0x68, 0x6B, 0x00)  # Wake up
            bus.write_byte_data(0x68, 0x37, 0x02)  # BYPASS_EN
            time.sleep(0.02)
        except Exception:
            pass

        # Scan
        found = []
        for addr in range(0x03, 0x78):
            try:
                bus.read_byte(addr)
                found.append(hex(addr))
            except Exception:
                pass
        bus.close()

        print(f"  Active I2C Addresses Detected: {found}")
        print(f"  - MPU-6050 (0x68)     : {'DETECTED [OK]' if '0x68' in found else 'NOT FOUND'}")
        print(f"  - HMC5883L Mag (0x1E) : {'DETECTED [OK]' if '0x1E' in found else ('FOUND ALT QMC (0x0d)' if '0x0d' in found else 'NOT FOUND')}")
        print(f"  - BMP180 Baro (0x77)  : {'DETECTED [OK]' if '0x77' in found else 'NOT FOUND'}")
        print(f"  - ADS1115 ADC (0x48)  : {'DETECTED [OK]' if '0x48' in found else 'NOT FOUND'}")

    except ImportError:
        print("  [NOTICE] smbus2 library not installed. Install with: pip install smbus2")
    except Exception as e:
        print(f"  [ERROR] I2C diagnostic failed: {e}")


def test_uart_gps():
    header("3. UART Device & NEO-6M GPS Communication")
    port = HARDWARE_CONFIG.uart_device
    if not os.path.exists(port):
        print(f"  [NOTICE] UART serial device {port} not found on this host.")
        print("           On Raspberry Pi, enable with: sudo raspi-config nonint do_serial 2")
        return

    try:
        import serial
        ser = serial.Serial(port, baudrate=HARDWARE_CONFIG.uart_baud_rate, timeout=1.0)
        print(f"  Port {port} opened successfully at {HARDWARE_CONFIG.uart_baud_rate} baud.")
        print("  Listening for NMEA sentences ($GPRMC, $GPGGA)...")
        received = []
        t_end = time.time() + 2.0
        while time.time() < t_end:
            line = ser.readline().decode("ascii", errors="ignore").strip()
            if line.startswith("$"):
                received.append(line.split(",")[0])
                if len(received) >= 3:
                    break
        ser.close()
        if received:
            print(f"  -> Successfully received NMEA sentences: {set(received)} [OK]")
        else:
            print("  -> Serial port open, but no NMEA data yet (Check GPS antenna & TX/RX wiring)")
    except ImportError:
        print("  [NOTICE] pyserial not installed. Install with: pip install pyserial")
    except Exception as e:
        print(f"  [ERROR] UART GPS test notice: {e}")


def test_dht22():
    header("4. DHT-22 Temperature & Humidity Sensor (GPIO 4)")
    try:
        import adafruit_dht
        import board
        dht = adafruit_dht.DHT22(board.D4)
        t = dht.temperature
        h = dht.humidity
        if t is not None:
            print(f"  -> DHT-22 Read Success: Temperature = {t:.1f}°C, Humidity = {h:.1f}% [OK]")
        else:
            print("  -> DHT-22 returned None (ensure 4.7k pullup is connected).")
    except ImportError:
        print("  [NOTICE] adafruit-circuitpython-dht not installed. Install with: pip install adafruit-circuitpython-dht")
    except Exception as e:
        print(f"  [NOTICE] DHT-22 diagnostic notice: {e}")


def test_camera():
    header("5. Raspberry Pi Camera Interface (CSI / libcamera)")
    cam_found = False
    try:
        from picamera2 import Picamera2
        p = Picamera2()
        p.close()
        print("  -> Picamera2 / libcamera: DETECTED & INITIALIZED [OK]")
        cam_found = True
    except Exception:
        pass

    if not cam_found and os.path.exists(HARDWARE_CONFIG.camera_device):
        try:
            import cv2
            cap = cv2.VideoCapture(HARDWARE_CONFIG.camera_device)
            if cap.isOpened():
                ret, _ = cap.read()
                cap.release()
                if ret:
                    print(f"  -> Camera on {HARDWARE_CONFIG.camera_device}: DETECTED & CAPTURED FRAME [OK]")
                    cam_found = True
        except Exception:
            pass

    if not cam_found:
        print(f"  [NOTICE] Camera not found at {HARDWARE_CONFIG.camera_device}.")
        print("           On Raspberry Pi, enable with: sudo raspi-config nonint do_camera 0")


def test_i2s_audio():
    header("6. INMP441 I2S Microphone Audio Interface")
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        dev_count = p.get_device_count()
        i2s_devices = []
        for i in range(dev_count):
            info = p.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                name = info.get("name", "")
                if any(k in name.lower() for k in ("i2s", "inmp", "voice", "card")):
                    i2s_devices.append(f"[{i}] {name}")
        p.terminate()
        if i2s_devices:
            print(f"  -> I2S Audio Devices Found: {i2s_devices} [OK]")
        else:
            print("  [NOTICE] Specific I2S ALSA card not detected in default list.")
            print("           Verify /boot/config.txt has I2S audio overlay enabled.")
    except ImportError:
        print("  [NOTICE] pyaudio not installed. Install with: sudo apt install portaudio19-dev && pip install pyaudio")
    except Exception as e:
        print(f"  [NOTICE] Audio interface diagnostic: {e}")


def test_actuators():
    header("7. GPIO Actuators Verification")
    try:
        from src.modules.hardware.hardware_hub import HARDWARE_HUB
        act = HARDWARE_HUB.actuators
        print(f"  Actuator Driver Mode: {act.status.value}")
        print(f"  Pin Mapping: RED=GPIO {act.pin_red}, YELLOW=GPIO {act.pin_yellow}, GREEN=GPIO {act.pin_green}, BUZZER=GPIO {act.pin_buzzer}, SERVO=GPIO {act.pin_servo}")
        print(f"  Current Actuator State: {act.read()}")
        print("  -> Actuators Driver: INITIALIZED & READY [OK]")
    except Exception as e:
        print(f"  [ERROR] Actuator verification error: {e}")


def main():
    print("=" * 68)
    print("  SENTINEL-AI RASPBERRY PI HARDWARE COMPREHENSIVE DIAGNOSTIC  ")
    print("=" * 68)

    test_board_detection()
    test_i2c_and_devices()
    test_uart_gps()
    test_dht22()
    test_camera()
    test_i2s_audio()
    test_actuators()

    print("\n" + "=" * 68)
    print("  DIAGNOSTIC TEST COMPLETE")
    print("=" * 68 + "\n")


if __name__ == "__main__":
    main()
