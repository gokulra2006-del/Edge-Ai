"""
Module 1 Hardware Foundation: GPIO & Hardware Bus Registry.
========================================================================
!! DEPRECATED !!
This module is SUPERSEDED by src/config/hardware_config.py which contains
the authoritative, conflict-free pin assignments matching the user's
physical wiring.

This file is kept ONLY for backward compatibility with old imports.
All pin values below have been updated to match hardware_config.py.

DO NOT add new pin assignments here. Use hardware_config.py instead.
========================================================================
"""
import warnings
from typing import Dict, Any, List

warnings.warn(
    "gpio_registry.py is DEPRECATED. Use src.config.hardware_config.HARDWARE_CONFIG.PINS instead.",
    DeprecationWarning,
    stacklevel=2
)


class GPIORegistry:
    """
    DEPRECATED: Use HARDWARE_CONFIG from src.config.hardware_config instead.
    Pin values updated to match the user's actual wiring (no conflicts with LCD).
    """

    # Updated to match hardware_config.py (the authoritative source)
    PIN_MAP = {
        # I2C Bus 1 (Physical Pins 3 & 5)
        "i2c_sda": {"bcm": 2, "physical": 3, "role": "I2C_SDA", "desc": "I2C Data for GY-87 & ADS1115"},
        "i2c_scl": {"bcm": 3, "physical": 5, "role": "I2C_SCL", "desc": "I2C Clock for GY-87 & ADS1115"},

        # Single-Wire Digital Sensor (Physical Pin 7)
        "dht22_data": {"bcm": 4, "physical": 7, "role": "INPUT", "desc": "DHT-22 Temperature & Humidity (4.7k pullup)"},

        # Traffic Signal LEDs — CORRECTED from old wrong pins
        "traffic_red": {"bcm": 5, "physical": 29, "role": "OUTPUT", "desc": "RED LED (330 ohm resistor)"},
        "traffic_yellow": {"bcm": 6, "physical": 31, "role": "OUTPUT", "desc": "YELLOW LED (330 ohm resistor)"},
        "traffic_green": {"bcm": 13, "physical": 33, "role": "OUTPUT", "desc": "GREEN LED (330 ohm resistor)"},

        # Emergency Barrier Servo (Hardware PWM0 - Physical Pin 32)
        "barrier_servo": {"bcm": 12, "physical": 32, "role": "PWM", "desc": "SG90 Access Barrier Servo Motor"},

        # Buzzer — CORRECTED from old wrong pin (was BCM 24 which is now LCD D5)
        "siren_buzzer": {"bcm": 16, "physical": 36, "role": "OUTPUT", "desc": "Buzzer module I/O"}
    }

    # I2C Addresses
    I2C_DEVICES = {
        "MPU6050_IMU": 0x68,
        "ADS1115_ADC": 0x48
    }

    @classmethod
    def validate_registry(cls) -> List[str]:
        """Validates that no duplicate BCM or physical pins are assigned."""
        errors = []
        seen_bcm = set()
        seen_phys = set()

        for name, pin_info in cls.PIN_MAP.items():
            bcm = pin_info["bcm"]
            phys = pin_info["physical"]

            if bcm in seen_bcm:
                errors.append(f"GPIO conflict: BCM {bcm} assigned multiple times (component: {name})")
            seen_bcm.add(bcm)

            if phys in seen_phys:
                errors.append(f"Physical pin conflict: Pin {phys} assigned multiple times (component: {name})")
            seen_phys.add(phys)

        return errors

    @classmethod
    def get_pin(cls, name: str) -> int:
        return cls.PIN_MAP[name]["bcm"]


GPIO_REGISTRY = GPIORegistry()
