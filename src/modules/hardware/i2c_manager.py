"""
Hardware Utility: Shared I2C Bus Manager.
==========================================
Provides a singleton I2C bus instance for all drivers on /dev/i2c-1.
Prevents multiple SMBus instances from conflicting.

Physical Pins:
- SDA = GPIO 2 / Physical Pin 3
- SCL = GPIO 3 / Physical Pin 5

Connected Devices (may not all be present):
- GY-87 board: MPU-6050 (0x68), HMC5883L (0x1E) or QMC5883L (0x0D), BMP180 (0x77)
- ADS1115 ADC: 0x48
"""
import os
import threading
from typing import Any, Dict, List, Optional


class I2CManager:
    """Thread-safe singleton I2C bus manager."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._bus = None
        self._bus_lock = threading.Lock()
        self.bus_number = 1
        self.device_path = "/dev/i2c-1"
        self.is_available = False
        self._detected_addresses: List[int] = []

    def open(self) -> bool:
        """Opens the I2C bus. Returns True if successful."""
        if self._bus is not None:
            return True

        if not os.path.exists(self.device_path):
            self.is_available = False
            return False

        try:
            import smbus2
            self._bus = smbus2.SMBus(self.bus_number)
            self.is_available = True
            return True
        except ImportError:
            # smbus2 not installed
            self.is_available = False
            return False
        except Exception:
            self.is_available = False
            return False

    def get_bus(self):
        """Returns the shared SMBus instance, opening if needed."""
        if self._bus is None:
            self.open()
        return self._bus

    def scan(self) -> List[int]:
        """
        Scans all valid I2C addresses (0x03 to 0x77).
        Returns a list of addresses that responded.

        IMPORTANT: Does not assume which devices exist.
        Run 'sudo i2cdetect -y 1' on the Pi for the same result.
        """
        if not self.open():
            return []

        found = []
        with self._bus_lock:
            for addr in range(0x03, 0x78):
                try:
                    self._bus.read_byte(addr)
                    found.append(addr)
                except Exception:
                    pass

        self._detected_addresses = found
        return found

    def is_device_present(self, address: int) -> bool:
        """Checks if a specific I2C device responds at the given address."""
        if not self.open():
            return False

        with self._bus_lock:
            try:
                self._bus.read_byte(address)
                return True
            except Exception:
                return False

    def read_byte(self, address: int) -> Optional[int]:
        """Thread-safe single byte read."""
        if not self._bus:
            return None
        with self._bus_lock:
            try:
                return self._bus.read_byte(address)
            except Exception:
                return None

    def write_byte_data(self, address: int, register: int, value: int) -> bool:
        """Thread-safe register write."""
        if not self._bus:
            return False
        with self._bus_lock:
            try:
                self._bus.write_byte_data(address, register, value)
                return True
            except Exception:
                return False

    def read_i2c_block_data(self, address: int, register: int, length: int) -> Optional[list]:
        """Thread-safe block read."""
        if not self._bus:
            return None
        with self._bus_lock:
            try:
                return self._bus.read_i2c_block_data(address, register, length)
            except Exception:
                return None

    def write_i2c_block_data(self, address: int, register: int, data: list) -> bool:
        """Thread-safe block write."""
        if not self._bus:
            return False
        with self._bus_lock:
            try:
                self._bus.write_i2c_block_data(address, register, data)
                return True
            except Exception:
                return False

    def get_scan_report(self) -> Dict[str, Any]:
        """Returns a human-readable scan report with known device identification."""
        addresses = self.scan()

        # Known device identification (but never assume they MUST exist)
        known_devices = {
            0x68: "MPU-6050 (Accelerometer/Gyroscope)",
            0x1E: "HMC5883L (Magnetometer)",
            0x0D: "QMC5883L (Alternative Magnetometer)",
            0x77: "BMP180 (Barometric Pressure/Temperature)",
            0x48: "ADS1115 (16-bit ADC for MQ-2)",
        }

        identified = {}
        unidentified = []
        for addr in addresses:
            if addr in known_devices:
                identified[hex(addr)] = known_devices[addr]
            else:
                unidentified.append(hex(addr))

        return {
            "bus": self.device_path,
            "bus_available": self.is_available,
            "total_devices_found": len(addresses),
            "addresses_hex": [hex(a) for a in addresses],
            "identified_devices": identified,
            "unidentified_addresses": unidentified,
        }

    def close(self):
        """Closes the I2C bus."""
        if self._bus:
            try:
                self._bus.close()
            except Exception:
                pass
            self._bus = None
            self.is_available = False


# Singleton instance
I2C_MANAGER = I2CManager()
