"""
Module 1: Abstract sensor interface.
Real hardware drivers (INMP441, MPU6050, Pi Camera) will inherit from this base class.
"""
from abc import ABC, abstractmethod
from typing import Any


class BaseSensor(ABC):
    @abstractmethod
    def initialize(self) -> bool:
        """Initializes the physical sensor or connection."""
        pass

    @abstractmethod
    def read(self) -> Any:
        """Returns the latest sensor reading."""
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """Safely shuts down the sensor."""
        pass
