"""
Hardware Abstraction Layer (HAL) for Sentinel-AI Raspberry Pi 4 Edge Node.
"""
from src.modules.hardware.base_driver import BaseHardwareDriver, DriverStatus
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
from src.modules.hardware.uart_manager import UART_MANAGER
from src.modules.hardware.hardware_hub import HardwareHub, get_hardware_hub

__all__ = [
    "BaseHardwareDriver",
    "DriverStatus",
    "DHT22Driver",
    "GY87Driver",
    "GPSDriver",
    "ADS1115Driver",
    "MQ2Driver",
    "INMP441Driver",
    "RaspberryPiCameraDriver",
    "LCDDriver",
    "ActuatorDriver",
    "I2C_MANAGER",
    "UART_MANAGER",
    "HardwareHub",
    "get_hardware_hub",
]
