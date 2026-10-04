"""
Hardware Abstraction Layer: Unified Hardware Management Hub.
============================================================
Coordinates all individual hardware drivers:
- DHT22 (GPIO 4)
- GY-87 10-DOF (I2C 0x68, 0x1E, 0x77)
- NEO-6M GPS (UART /dev/serial0)
- ADS1115 ADC (I2C 0x48)
- MQ-2 Gas/Smoke (via ADS1115 A0 with voltage divider)
- INMP441 (I2S Pins 18, 19, 20)
- Raspberry Pi Camera (CSI / V4L2)
- LCD 16x2 (GPIO 21-26, 4-bit mode)
- Actuators (LEDs 5, 6, 13; Buzzer 16; Servo 12)

Provides unified telemetry, diagnostic reports, and fault-tolerant operation.
Each sensor failure is ISOLATED — the system continues operating.
"""
import time
from typing import Any, Dict
from src.modules.hardware.dht22_driver import DHT22Driver
from src.modules.hardware.gy87_driver import GY87Driver
from src.modules.hardware.gps_driver import GPSDriver
from src.modules.hardware.ads1115_driver import ADS1115Driver
from src.modules.hardware.mq2_driver import MQ2Driver
from src.modules.hardware.inmp441_driver import INMP441Driver
from src.modules.hardware.camera_driver import RaspberryPiCameraDriver
from src.modules.hardware.lcd_driver import LCDDriver
from src.modules.hardware.actuator_driver import ActuatorDriver
from src.modules.hardware.i2c_manager import I2C_MANAGER
from src.config.hardware_config import HARDWARE_CONFIG
from src.modules.logging.logger import LOGGER


class HardwareHub:
    """Master orchestrator for all Sentinel-AI edge hardware devices."""

    def __init__(self):
        LOGGER.info("=== Initializing SENTINEL-AI Hardware Hub ===")

        # Initialize drivers — each one handles its own failure gracefully
        self.dht22 = DHT22Driver()
        self.gy87 = GY87Driver()
        self.gps = GPSDriver()
        self.ads1115 = ADS1115Driver()
        self.mq2 = MQ2Driver(self.ads1115)  # MQ-2 depends on ADS1115
        self.inmp441 = INMP441Driver()
        self.camera = RaspberryPiCameraDriver()
        self.lcd = LCDDriver()
        self.actuators = ActuatorDriver()

        # Log initialization summary
        drivers = self._get_all_drivers()
        online = sum(1 for d in drivers if not d.is_simulated)
        simulated = sum(1 for d in drivers if d.is_simulated)
        LOGGER.info(f"Hardware Hub initialized: {online} physical, {simulated} simulated")

    def _get_all_drivers(self):
        """Returns list of all driver instances."""
        return [
            self.dht22, self.gy87, self.gps, self.ads1115,
            self.mq2, self.inmp441, self.camera, self.lcd, self.actuators
        ]

    def get_unified_telemetry(self) -> Dict[str, Any]:
        """
        Builds the unified telemetry structure as specified.
        Each sensor read is wrapped in try/except — one sensor failure
        does NOT crash the entire telemetry collection.
        """
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # DHT22
        try:
            dht_data = self.dht22.read()
        except Exception:
            dht_data = {"temperature_c": None, "humidity_pct": None,
                        "quality": {"status": "ERROR", "is_simulated": True}}

        # GY-87 IMU
        try:
            imu_data = self.gy87.read()
        except Exception:
            imu_data = {"quality": {"status": "ERROR", "is_simulated": True}}

        # Gas/Smoke (MQ-2)
        try:
            gas_data = self.mq2.read()
        except Exception:
            gas_data = {"quality": {"status": "ERROR", "is_simulated": True}}

        # GPS
        try:
            gps_data = self.gps.read()
        except Exception:
            gps_data = {"quality": {"status": "ERROR", "is_simulated": True}}

        # Audio (INMP441)
        try:
            audio_data = self.inmp441.read()
        except Exception:
            audio_data = {"quality": {"status": "ERROR", "is_simulated": True}}

        # Camera
        try:
            cam_data = self.camera.read()
        except Exception:
            cam_data = {"quality": {"status": "ERROR", "is_simulated": True}}

        # Actuators
        try:
            act_data = self.actuators.read()
        except Exception:
            act_data = {"quality": {"status": "ERROR", "is_simulated": True}}

        # Build unified telemetry format
        return {
            "timestamp": now_iso,
            "temperature": dht_data.get("temperature_c"),
            "humidity": dht_data.get("humidity_pct"),

            "imu": {
                "accelerometer": imu_data.get("accelerometer_g", {}),
                "gyroscope": imu_data.get("gyroscope_dps", {}),
                "magnetometer": {"heading_deg": imu_data.get("compass_heading_deg")},
                "pressure": imu_data.get("barometric_pressure_hpa"),
                "altitude": imu_data.get("barometric_altitude_m"),
                "impact_detected": imu_data.get("impact_detected", False),
                "composite_g": imu_data.get("composite_g", 0.0),
                "status": imu_data.get("quality", {}).get("status", "UNKNOWN"),
            },

            "gas": {
                "raw_adc": gas_data.get("raw_adc"),
                "adc_voltage": gas_data.get("adc_voltage"),
                "estimated_sensor_voltage": gas_data.get("estimated_sensor_voltage"),
                "relative_gas_level": gas_data.get("relative_gas_level"),
                "is_warm": gas_data.get("is_warm", False),
                "status": gas_data.get("quality", {}).get("status", "UNKNOWN"),
                "note": "Relative sensor level (NOT calibrated PPM)",
            },

            "gps": {
                "latitude": gps_data.get("latitude"),
                "longitude": gps_data.get("longitude"),
                "altitude": gps_data.get("altitude_m"),
                "speed": gps_data.get("speed_kmh"),
                "satellites": gps_data.get("satellites", 0),
                "fix": gps_data.get("fix_valid", False),
                "fix_status": gps_data.get("fix_status", "UNKNOWN"),
                "utc_time": gps_data.get("utc_time"),
                "status": gps_data.get("quality", {}).get("status", "UNKNOWN"),
            },

            "audio": {
                "rms": audio_data.get("rms_amplitude"),
                "level_db": audio_data.get("level_db"),
                "status": audio_data.get("quality", {}).get("status", "UNKNOWN"),
            },

            "actuators": {
                "red_led": act_data.get("leds", {}).get("red", False),
                "yellow_led": act_data.get("leds", {}).get("yellow", False),
                "green_led": act_data.get("leds", {}).get("green", False),
                "buzzer": act_data.get("buzzer", {}).get("active", False),
                "servo_angle": act_data.get("servo", {}).get("angle", 90),
            },

            "system": {
                "camera": cam_data.get("quality", {}).get("status", "UNKNOWN"),
                "i2c": "AVAILABLE" if I2C_MANAGER.is_available else "NOT_AVAILABLE",
                "uart": gps_data.get("quality", {}).get("status", "UNKNOWN"),
                "lcd": self.lcd.status.value,
            }
        }

    def get_system_health(self) -> Dict[str, Any]:
        """Generates comprehensive driver and hardware interface health report."""
        drivers = self._get_all_drivers()
        physical_online_count = sum(1 for d in drivers if not d.is_simulated)
        simulated_count = sum(1 for d in drivers if d.is_simulated)

        return {
            "board": HARDWARE_CONFIG.board_model,
            "architecture": HARDWARE_CONFIG.architecture,
            "operating_mode": "HARDWARE" if physical_online_count > 0 else "SIMULATION",
            "physical_devices_online": physical_online_count,
            "simulated_devices_active": simulated_count,
            "drivers": {d.driver_name: d.get_health() for d in drivers}
        }

    def cleanup(self):
        """Cleans up all hardware drivers safely."""
        LOGGER.info("=== Cleaning up SENTINEL-AI Hardware Hub ===")
        try:
            self.lcd.cleanup()
        except Exception:
            pass
        try:
            self.inmp441.cleanup()
        except Exception:
            pass
        try:
            self.camera.cleanup()
        except Exception:
            pass
        try:
            self.gps.cleanup()
        except Exception:
            pass
        try:
            self.actuators.cleanup()
        except Exception:
            pass
        try:
            I2C_MANAGER.close()
        except Exception:
            pass
        LOGGER.info("Hardware Hub cleanup complete.")


# Lazy singleton — not instantiated at import time
_hardware_hub_instance = None

def get_hardware_hub() -> HardwareHub:
    """Returns the singleton HardwareHub, creating it on first call."""
    global _hardware_hub_instance
    if _hardware_hub_instance is None:
        _hardware_hub_instance = HardwareHub()
    return _hardware_hub_instance


class _HardwareHubProxy:
    """Proxy object allowing module-level HARDWARE_HUB usage while preserving lazy loading."""
    def __getattr__(self, name):
        return getattr(get_hardware_hub(), name)


HARDWARE_HUB = _HardwareHubProxy()
