"""
Hardware Driver: DHT-22 Temperature and Humidity Sensor.
========================================================
Hardware Pin: GPIO 4 (Physical Pin 7)
Protocol: Single-wire digital with 4.7k pull-up to 3.3V

Handles physical 2-second rate-limiting and provides calibrated simulation fallback.
"""
import random
import time
from typing import Any, Dict
from src.modules.hardware.base_driver import BaseHardwareDriver, DriverStatus
from src.config.hardware_config import HARDWARE_CONFIG


class DHT22Driver(BaseHardwareDriver):
    def __init__(self):
        super().__init__("DHT22_Sensor", "Environmental_Temperature_Humidity")
        self.pin_bcm = HARDWARE_CONFIG.PINS["dht22_data"].bcm
        self._dht_device = None
        self._last_temp = 28.5
        self._last_humidity = 55.0
        self._last_physical_read = 0.0
        self._consecutive_fails = 0
        self.initialize()

    def initialize(self) -> bool:
        try:
            import adafruit_dht
            import board
            # Map GPIO 4 to board.D4
            pin_attr = getattr(board, f"D{self.pin_bcm}", None)
            if pin_attr:
                self._dht_device = adafruit_dht.DHT22(pin_attr)
                self.status = DriverStatus.ONLINE
                self.is_simulated = False
                self.error_message = None
                return True
        except (ImportError, RuntimeError, Exception) as e:
            self.error_message = f"DHT22 hardware uninitialized ({e}); using simulation mode."

        self.status = DriverStatus.SIMULATED
        self.is_simulated = True
        return False

    def read(self) -> Dict[str, Any]:
        self.read_count += 1
        now = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

        if not self.is_simulated and self._dht_device:
            # Enforce 2.0s physical cooldown
            if now - self._last_physical_read >= HARDWARE_CONFIG.POLL_INTERVALS["dht22"]:
                try:
                    t = self._dht_device.temperature
                    h = self._dht_device.humidity
                    if t is not None and h is not None:
                        t_val = float(t)
                        h_val = float(h)
                        # Validate: DHT22 range is -40 to 80°C, 0 to 100% RH
                        if t_val < -40.0 or t_val > 80.0:
                            self.failure_count += 1
                            self.error_message = f"Invalid temperature: {t_val}°C (outside -40 to 80)"
                            self.status = DriverStatus.DEGRADED
                        elif h_val < 0.0 or h_val > 100.0:
                            self.failure_count += 1
                            self.error_message = f"Invalid humidity: {h_val}% (outside 0 to 100)"
                            self.status = DriverStatus.DEGRADED
                        else:
                            self._last_temp = round(t_val, 2)
                            self._last_humidity = round(h_val, 2)
                            self._last_physical_read = now
                            self.status = DriverStatus.ONLINE
                            self.last_read_time = now
                            self._consecutive_fails = 0
                    else:
                        self._consecutive_fails += 1
                        self.error_message = "DHT22 returned None (sensor timeout)"
                except RuntimeError as re:
                    # DHT sensors commonly fail occasional checksums; maintain last valid reading
                    self._consecutive_fails += 1
                    self.status = DriverStatus.DEGRADED
                    self.error_message = f"DHT read transient warning: {re}"
                except Exception as e:
                    self._consecutive_fails += 1
                    self.failure_count += 1
                    self.status = DriverStatus.DEGRADED
                    self.error_message = str(e)

                # If too many consecutive failures, mark as OFFLINE
                if self._consecutive_fails >= 10:
                    self.status = DriverStatus.OFFLINE
                    self.error_message = f"DHT22 offline after {self._consecutive_fails} consecutive failures"

            return {
                "temperature_c": self._last_temp,
                "humidity_pct": self._last_humidity,
                "heat_index_c": round(self._last_temp + (0.05 * self._last_humidity), 2),
                "timestamp": now_iso,
                "quality": {
                    "status": self.status.value,
                    "is_simulated": False,
                    "source": "physical_gpio_4"
                }
            }

        # Simulation Mode
        noise_t = random.uniform(-0.15, 0.15)
        noise_h = random.uniform(-0.4, 0.4)
        sim_temp = round(28.5 + noise_t, 2)
        sim_hum = round(54.0 + noise_h, 2)
        self.last_read_time = now

        return {
            "temperature_c": sim_temp,
            "humidity_pct": sim_hum,
            "heat_index_c": round(sim_temp + (0.05 * sim_hum), 2),
            "timestamp": now_iso,
            "quality": {
                "status": DriverStatus.SIMULATED.value,
                "is_simulated": True,
                "source": "simulated_dht22"
            }
        }
