"""
Hardware Abstraction Layer: Base Driver Interface.
==================================================
Declares the contract implemented by all hardware sensor and actuator drivers.
Guarantees strict labeling of real vs simulated readings.
"""
from abc import ABC, abstractmethod
from enum import Enum
import time
from typing import Any, Dict, Optional


class DriverStatus(str, Enum):
    ONLINE = "ONLINE"            # Physical hardware connected and communicating cleanly
    SIMULATED = "SIMULATED"      # Running in software simulation fallback mode
    DEGRADED = "DEGRADED"        # Sensor communication errors or intermittent parity failures
    OFFLINE = "OFFLINE"          # Interface disabled or device communication failed
    WARMING_UP = "WARMING_UP"    # Sensor requires warm-up period (e.g., MQ-2 gas heater)
    NO_FIX = "NO_FIX"            # GPS receiver online but has no satellite fix yet
    NOT_DETECTED = "NOT_DETECTED"  # Hardware not found on scan (I2C address absent, etc.)


class BaseHardwareDriver(ABC):
    """Abstract base class for all Sentinel-AI hardware drivers."""

    def __init__(self, driver_name: str, device_type: str):
        self.driver_name = driver_name
        self.device_type = device_type
        self.status: DriverStatus = DriverStatus.SIMULATED
        self.is_simulated: bool = True
        self.last_read_time: float = 0.0
        self.error_message: Optional[str] = None
        self.read_count: int = 0
        self.failure_count: int = 0

    @abstractmethod
    def initialize(self) -> bool:
        """Initializes the physical hardware driver. Returns True if physical device ready."""
        pass

    @abstractmethod
    def read(self) -> Dict[str, Any]:
        """Reads normalized telemetry dictionary from sensor."""
        pass

    def get_health(self) -> Dict[str, Any]:
        """Returns standard health metadata for this driver."""
        return {
            "driver_name": self.driver_name,
            "device_type": self.device_type,
            "status": self.status.value,
            "is_simulated": self.is_simulated,
            "read_count": self.read_count,
            "failure_count": self.failure_count,
            "last_read_time": self.last_read_time,
            "error_message": self.error_message
        }
