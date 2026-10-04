"""
Hardware Driver: MQ-2 Gas/Smoke Sensor (via ADS1115 ADC).
=========================================================
The MQ-2 sensor measures combustible gases and smoke.

ELECTRICAL CONNECTIONS:
- MQ-2 VCC  -> Physical Pin 2 (5V)          — heater needs 5V
- MQ-2 GND  -> Common GND
- MQ-2 DOUT -> UNUSED
- MQ-2 AOUT -> Voltage divider -> ADS1115 A0

VOLTAGE DIVIDER (required — DO NOT connect MQ-2 AOUT directly to Pi GPIO):
    MQ-2 AOUT ──── 10kΩ resistor ──┬── ADS1115 A0
                                    │
                                20kΩ resistor
                                    │
                                   GND

    Ratio: Vadc = Vmq2 × 20k / (10k + 20k) = Vmq2 × 1/3
    This scales the 0-5V MQ-2 output down to 0-1.67V, safe for ADS1115 at 3.3V VDD.

IMPORTANT ABOUT READINGS:
- The MQ-2 is a resistive sensor. Its resistance changes with gas concentration.
- Without laboratory calibration against known gas concentrations, the voltage
  reading is a RELATIVE INDICATOR of gas/smoke presence, NOT an accurate PPM value.
- This driver reports: raw ADC, measured voltage, estimated original voltage,
  and a relative gas level (0-100 scale) for threshold comparison.
- It does NOT claim PPM accuracy.
"""
import time
from typing import Any, Dict
from src.modules.hardware.base_driver import BaseHardwareDriver, DriverStatus
from src.modules.hardware.ads1115_driver import ADS1115Driver
from src.config.hardware_config import HARDWARE_CONFIG


class MQ2Driver(BaseHardwareDriver):
    """
    Gas/smoke sensor driver. Reads analog voltage from MQ-2 via ADS1115 ADC.

    All readings are labeled as RELATIVE levels (not PPM) because the sensor
    is not calibrated. A higher voltage = more gas/smoke detected.
    """

    def __init__(self, ads1115: ADS1115Driver):
        super().__init__("MQ2_Gas_Smoke", "Gas_Smoke_Sensor")
        self._ads1115 = ads1115
        self._channel = HARDWARE_CONFIG.MQ2_ADS1115_CHANNEL
        self._divider_ratio = HARDWARE_CONFIG.MQ2_VOLTAGE_DIVIDER_RATIO
        self._warmup_seconds = HARDWARE_CONFIG.MQ2_WARMUP_SECONDS
        self._start_time = time.time()
        self._is_warmed_up = False
        self.initialize()

    def initialize(self) -> bool:
        """Checks if ADS1115 is available for MQ-2 readings."""
        if self._ads1115.status == DriverStatus.ONLINE:
            self.is_simulated = False
            self.error_message = None
            # Start in WARMING_UP state
            self.status = DriverStatus.WARMING_UP
            self._start_time = time.time()
            return True

        self.error_message = "ADS1115 ADC not available — cannot read MQ-2 sensor"
        self.status = DriverStatus.NOT_DETECTED
        self.is_simulated = True
        return False

    def _check_warmup(self):
        """Updates warm-up status. MQ-2 heaters need ~60 seconds to stabilize."""
        if self._is_warmed_up:
            return
        elapsed = time.time() - self._start_time
        if elapsed >= self._warmup_seconds:
            self._is_warmed_up = True
            if not self.is_simulated:
                self.status = DriverStatus.ONLINE

    def read(self) -> Dict[str, Any]:
        """
        Reads gas/smoke level from MQ-2 via ADS1115 channel 0.

        Returns:
            raw_adc: Raw 16-bit ADC reading
            adc_voltage: Voltage measured at ADS1115 A0 (after voltage divider)
            estimated_sensor_voltage: Estimated original MQ-2 AOUT voltage (before divider)
            relative_gas_level: 0-100 scale relative indicator
            is_warm: Whether the sensor has completed warm-up
            status: Current driver status
        """
        self.read_count += 1
        self._check_warmup()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Get raw ADC reading
        adc_result = self._ads1115.read_channel(self._channel)

        if not adc_result.get("is_simulated", True):
            adc_voltage = adc_result["voltage"]
            raw_adc = adc_result["raw_adc"]

            # Reconstruct the original MQ-2 sensor voltage (before voltage divider)
            # divider_ratio = Vadc / Vsensor, so Vsensor = Vadc / divider_ratio
            if self._divider_ratio > 0:
                estimated_sensor_voltage = round(adc_voltage / self._divider_ratio, 3)
            else:
                estimated_sensor_voltage = adc_voltage

            # Relative gas level: scale the estimated sensor voltage to 0-100
            # MQ-2 output range is roughly 0.1V (clean air) to 4.0V (heavy gas)
            # This is NOT PPM — it is a unitless relative indicator
            relative_level = min(100.0, max(0.0, (estimated_sensor_voltage / 4.0) * 100.0))

            # Detect abnormal readings (disconnected sensor reads ~0V or rail voltage)
            is_abnormal = adc_voltage < 0.01 or adc_voltage > 3.2

            warmup_remaining = max(0, self._warmup_seconds - (time.time() - self._start_time))

            self.last_read_time = time.time()
            return {
                "raw_adc": raw_adc,
                "adc_voltage": round(adc_voltage, 4),
                "estimated_sensor_voltage": estimated_sensor_voltage,
                "relative_gas_level": round(relative_level, 1),
                "is_warm": self._is_warmed_up,
                "warmup_remaining_seconds": round(warmup_remaining, 0),
                "is_abnormal": is_abnormal,
                "timestamp": now_iso,
                "quality": {
                    "status": self.status.value,
                    "is_simulated": False,
                    "source": "physical_mq2_via_ads1115_a0",
                    "note": "Relative gas level (NOT calibrated PPM). Higher = more gas detected.",
                    "voltage_divider": "10k/20k (ratio 1:3)"
                }
            }

        # Simulation fallback
        import random
        sim_voltage = round(0.15 + random.uniform(-0.02, 0.05), 4)
        return {
            "raw_adc": int(sim_voltage / 4.096 * 32768),
            "adc_voltage": sim_voltage,
            "estimated_sensor_voltage": round(sim_voltage / self._divider_ratio, 3) if self._divider_ratio > 0 else sim_voltage,
            "relative_gas_level": round(min(100, max(0, (sim_voltage / self._divider_ratio / 4.0) * 100)), 1) if self._divider_ratio > 0 else 0.0,
            "is_warm": True,
            "warmup_remaining_seconds": 0,
            "is_abnormal": False,
            "timestamp": now_iso,
            "quality": {
                "status": DriverStatus.SIMULATED.value,
                "is_simulated": True,
                "source": "simulated_mq2",
                "note": "Simulated relative gas level (NOT calibrated PPM)"
            }
        }
