"""
Hardware Driver: ADS1115 16-Bit ADC (Pure Analog-to-Digital Converter).
======================================================================
Physical Interface: /dev/i2c-1 (Address 0x48)
Pins: SDA = GPIO 2 / Physical Pin 3, SCL = GPIO 3 / Physical Pin 5

This is a PURE ADC driver. It reads raw ADC values and converts to voltage.
Gas/smoke interpretation is handled separately by mq2_driver.py.

Channel AIN0 is connected to MQ-2 gas sensor through a voltage divider.
Channels AIN1-AIN3 are currently unused.
"""
import time
from typing import Any, Dict, Optional
from src.modules.hardware.base_driver import BaseHardwareDriver, DriverStatus
from src.modules.hardware.i2c_manager import I2C_MANAGER
from src.config.hardware_config import HARDWARE_CONFIG


# ADS1115 register and config constants
ADS1115_REG_CONVERSION = 0x00
ADS1115_REG_CONFIG = 0x01

# Config word components for single-shot mode
# Bits: OS(1) MUX(3) PGA(3) MODE(1) | DR(3) COMP_MODE(1) COMP_POL(1) COMP_LAT(1) COMP_QUE(2)
# Channel configs (MUX bits 14:12) for single-ended readings:
ADS1115_MUX_AIN0 = 0x4000  # AIN0 vs GND
ADS1115_MUX_AIN1 = 0x5000  # AIN1 vs GND
ADS1115_MUX_AIN2 = 0x6000  # AIN2 vs GND
ADS1115_MUX_AIN3 = 0x7000  # AIN3 vs GND

# PGA (Programmable Gain Amplifier) settings:
ADS1115_PGA_4096 = 0x0200   # +/- 4.096V range (1 bit = 0.125mV)

# Operating mode
ADS1115_MODE_SINGLE = 0x0100  # Single-shot mode

# Data rate: 128 SPS
ADS1115_DR_128 = 0x0080

# Comparator disabled
ADS1115_COMP_DISABLE = 0x0003

# Start conversion
ADS1115_OS_START = 0x8000

# Default config: AIN0, +/-4.096V, single-shot, 128SPS, comparator off
ADS1115_DEFAULT_CONFIG = (
    ADS1115_OS_START | ADS1115_MUX_AIN0 | ADS1115_PGA_4096 |
    ADS1115_MODE_SINGLE | ADS1115_DR_128 | ADS1115_COMP_DISABLE
)

CHANNEL_MUX = {
    0: ADS1115_MUX_AIN0,
    1: ADS1115_MUX_AIN1,
    2: ADS1115_MUX_AIN2,
    3: ADS1115_MUX_AIN3,
}


class ADS1115Driver(BaseHardwareDriver):
    """
    Pure ADC driver for the ADS1115 16-bit analog-to-digital converter.

    Returns raw ADC counts and calculated voltage — does NOT interpret
    what the voltage means (that is the job of sensor-specific drivers
    like mq2_driver.py).
    """

    def __init__(self):
        super().__init__("ADS1115_ADC", "Analog_Digital_Converter")
        self.i2c_addr = HARDWARE_CONFIG.I2C_ADDRESSES["ADS1115"]
        self.initialize()

    def initialize(self) -> bool:
        """Detects the ADS1115 on the I2C bus."""
        if I2C_MANAGER.is_device_present(self.i2c_addr):
            self.status = DriverStatus.ONLINE
            self.is_simulated = False
            self.error_message = None
            return True

        self.error_message = f"ADS1115 ADC not detected at {hex(self.i2c_addr)}"
        self.status = DriverStatus.NOT_DETECTED
        self.is_simulated = True
        return False

    def read_channel(self, channel: int = 0) -> Dict[str, Any]:
        """
        Reads a single channel from the ADS1115.

        Args:
            channel: ADC channel 0-3 (AIN0-AIN3)

        Returns:
            Dict with raw_adc (16-bit signed), voltage (float), and status info.
        """
        self.read_count += 1
        now = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

        if channel not in CHANNEL_MUX:
            return {
                "raw_adc": 0,
                "voltage": 0.0,
                "channel": channel,
                "error": f"Invalid channel {channel}. Must be 0-3.",
                "timestamp": now_iso,
                "status": DriverStatus.OFFLINE.value,
                "is_simulated": True,
            }

        if not self.is_simulated:
            try:
                # Build config word for the requested channel
                config = (
                    ADS1115_OS_START | CHANNEL_MUX[channel] | ADS1115_PGA_4096 |
                    ADS1115_MODE_SINGLE | ADS1115_DR_128 | ADS1115_COMP_DISABLE
                )
                config_bytes = [(config >> 8) & 0xFF, config & 0xFF]

                # Write config to start conversion
                if not I2C_MANAGER.write_i2c_block_data(self.i2c_addr, ADS1115_REG_CONFIG, config_bytes):
                    raise IOError("Failed to write ADS1115 config register")

                # Wait for conversion (128 SPS = ~8ms per sample)
                time.sleep(0.01)

                # Read result
                result = I2C_MANAGER.read_i2c_block_data(self.i2c_addr, ADS1115_REG_CONVERSION, 2)
                if result is None:
                    raise IOError("Failed to read ADS1115 conversion register")

                raw_adc = (result[0] << 8) | result[1]
                # Handle sign for 16-bit signed value
                if raw_adc > 32767:
                    raw_adc -= 65536

                # Convert to voltage: PGA = 4.096V, 16-bit signed = 32768 levels
                voltage = (raw_adc / 32768.0) * 4.096

                self.last_read_time = now
                self.status = DriverStatus.ONLINE
                return {
                    "raw_adc": raw_adc,
                    "voltage": round(voltage, 4),
                    "raw_adc_voltage": round(voltage, 4),
                    "smoke_ppm": 0.0,
                    "hazard_detected": False,
                    "channel": channel,
                    "pga_range_v": 4.096,
                    "timestamp": now_iso,
                    "status": DriverStatus.ONLINE.value,
                    "is_simulated": False,
                    "source": "physical_ads1115",
                }

            except Exception as e:
                self.failure_count += 1
                self.status = DriverStatus.DEGRADED
                self.error_message = str(e)

        # Simulation fallback
        import random
        sim_voltage = round(0.15 + random.uniform(-0.02, 0.02), 4)
        return {
            "raw_adc": int(sim_voltage / 4.096 * 32768),
            "voltage": sim_voltage,
            "raw_adc_voltage": sim_voltage,
            "smoke_ppm": 0.0,
            "hazard_detected": False,
            "channel": channel,
            "pga_range_v": 4.096,
            "timestamp": now_iso,
            "status": DriverStatus.SIMULATED.value,
            "is_simulated": True,
            "source": "simulated_ads1115",
        }

    def read(self) -> Dict[str, Any]:
        """Default read — returns channel 0 (MQ-2 connection)."""
        return self.read_channel(0)
