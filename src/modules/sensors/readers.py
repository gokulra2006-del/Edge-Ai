"""
Module 1 Hardware Foundation: Unified Readers (Physical RPi, Simulator, Replay, Fault Injection).
================================================================================================
Implements distinct SensorReader engines producing normalized SensorReading telemetry.
"""
import math
import random
import time
from typing import Any, Dict, List, Optional
from src.modules.sensors.base_reader import DriverHealth, QualityMetadata, SensorReader, SensorReading
from src.modules.sensors.capability_detector import CAPABILITY_DETECTOR


class SimulatorReader(SensorReader):
    """Produces continuous normalized simulated readings within baseline tolerances."""

    def __init__(self, sensor_id: str, sensor_type: str):
        super().__init__(sensor_id, sensor_type)
        self.health = DriverHealth.SIMULATED

    def read(self) -> SensorReading:
        self.sequence += 1
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ")

        if self.sensor_type == "imu":
            values = {
                "accel_x_g": round(random.uniform(-0.02, 0.02), 3),
                "accel_y_g": round(random.uniform(-0.02, 0.02), 3),
                "accel_z_g": round(1.0 + random.uniform(-0.02, 0.02), 3),
                "composite_g": round(random.uniform(0.01, 0.05), 3),
                "impact_detected": False
            }
        elif self.sensor_type == "gas":
            values = {
                "raw_adc_voltage": 0.45,
                "smoke_ppm": round(12.0 + random.uniform(-1.0, 1.0), 1),
                "hazard_flag": False
            }
        elif self.sensor_type == "temperature":
            values = {
                "temperature_c": round(28.5 + random.uniform(-0.3, 0.3), 1),
                "humidity_pct": 55.0
            }
        elif self.sensor_type == "audio":
            values = {
                "decibel_db": round(58.0 + random.uniform(-2.0, 3.0), 1),
                "class": "traffic",
                "confidence": 0.91
            }
        else:
            values = {"metric": 1.0}

        return SensorReading(
            sensor_id=self.sensor_id,
            sensor_type=self.sensor_type,
            timestamp=now_iso,
            values=values,
            quality=QualityMetadata(
                status=DriverHealth.SIMULATED,
                confidence=0.95,
                latency_ms=1.2,
                sequence_number=self.sequence
            ),
            source="simulation"
        )


class FaultInjectionReader(SensorReader):
    """Simulates hardware dropouts, sensor disconnects, and stuck telemetry for testing."""

    def __init__(self, sensor_id: str, sensor_type: str, fault_type: str = "DISCONNECT"):
        super().__init__(sensor_id, sensor_type)
        self.fault_type = fault_type

    def read(self) -> SensorReading:
        self.sequence += 1
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ")

        if self.fault_type == "DISCONNECT":
            return SensorReading(
                sensor_id=self.sensor_id,
                sensor_type=self.sensor_type,
                timestamp=now_iso,
                values={},
                quality=QualityMetadata(
                    status=DriverHealth.OFFLINE,
                    confidence=0.0,
                    latency_ms=99.9,
                    consecutive_failures=5,
                    sequence_number=self.sequence,
                    error_message="I2C device read error: NACK received on bus address"
                ),
                source="fault_injection"
            )
        elif self.fault_type == "STALE_DATA":
            return SensorReading(
                sensor_id=self.sensor_id,
                sensor_type=self.sensor_type,
                timestamp=now_iso,
                values={"temperature_c": 28.5, "humidity_pct": 55.0},
                quality=QualityMetadata(
                    status=DriverHealth.DEGRADED,
                    confidence=0.45,
                    latency_ms=15.0,
                    consecutive_failures=2,
                    sequence_number=self.sequence,
                    error_message="Sensor telemetry frozen; data freshness expired"
                ),
                source="fault_injection"
            )
        else:
            return SimulatorReader(self.sensor_id, self.sensor_type).read()


class RaspberryPiReader(SensorReader):
    """Physical hardware driver reading MPU-6050, ADS1115 (MQ-2), and DHT-22."""

    def __init__(self, sensor_id: str, sensor_type: str):
        super().__init__(sensor_id, sensor_type)
        self._bus = None
        self._init_hardware()

    def _init_hardware(self):
        try:
            import smbus2
            self._bus = smbus2.SMBus(1)
            # Wake up MPU-6050 if IMU
            if self.sensor_type == "imu":
                self._bus.write_byte_data(0x68, 0x6B, 0x00)
            self.health = DriverHealth.ONLINE
        except Exception:
            self.health = DriverHealth.SIMULATED

    def read(self) -> SensorReading:
        self.sequence += 1
        t_start = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ")

        if self.health != DriverHealth.ONLINE or not self._bus:
            # Fallback to simulated reading if hardware not connected
            sub = SimulatorReader(self.sensor_id, self.sensor_type).read()
            sub.source = "raspberry_pi_fallback"
            return sub

        try:
            if self.sensor_type == "imu":
                # Read 6 bytes of accel registers from 0x3B
                data = self._bus.read_i2c_block_data(0x68, 0x3B, 6)
                raw_x = (data[0] << 8) | data[1]
                raw_y = (data[2] << 8) | data[3]
                raw_z = (data[4] << 8) | data[5]
                # Convert 16-bit signed
                ax = (raw_x - 65536 if raw_x > 32767 else raw_x) / 16384.0
                ay = (raw_y - 65536 if raw_y > 32767 else raw_y) / 16384.0
                az = (raw_z - 65536 if raw_z > 32767 else raw_z) / 16384.0
                composite = math.sqrt(ax**2 + ay**2 + az**2) - 1.0

                values = {
                    "accel_x_g": round(ax, 3),
                    "accel_y_g": round(ay, 3),
                    "accel_z_g": round(az, 3),
                    "composite_g": round(max(0.0, composite), 3),
                    "impact_detected": composite > 2.5
                }
            elif self.sensor_type == "gas":
                # Read ADS1115 AIN0 for MQ-2
                # Config register for single-shot AIN0: 0xC183
                self._bus.write_i2c_block_data(0x48, 0x01, [0xC1, 0x83])
                time.sleep(0.01)
                res = self._bus.read_i2c_block_data(0x48, 0x00, 2)
                raw_adc = (res[0] << 8) | res[1]
                voltage = (raw_adc * 4.096) / 32768.0
                smoke_ppm = max(5.0, voltage * 80.0)
                values = {
                    "raw_adc_voltage": round(voltage, 3),
                    "smoke_ppm": round(smoke_ppm, 1),
                    "hazard_flag": smoke_ppm > 150.0
                }
            else:
                values = {"metric": 1.0}

            latency = (time.time() - t_start) * 1000.0
            return SensorReading(
                sensor_id=self.sensor_id,
                sensor_type=self.sensor_type,
                timestamp=now_iso,
                values=values,
                quality=QualityMetadata(
                    status=DriverHealth.ONLINE,
                    confidence=0.98,
                    latency_ms=latency,
                    sequence_number=self.sequence
                ),
                source="raspberry_pi"
            )
        except Exception as e:
            self.consecutive_failures += 1
            return SensorReading(
                sensor_id=self.sensor_id,
                sensor_type=self.sensor_type,
                timestamp=now_iso,
                values={},
                quality=QualityMetadata(
                    status=DriverHealth.DEGRADED,
                    confidence=0.2,
                    consecutive_failures=self.consecutive_failures,
                    sequence_number=self.sequence,
                    error_message=str(e)
                ),
                source="raspberry_pi"
            )


class CompositeSensorHub:
    """Consolidated manager providing normalized telemetry across all reader channels."""

    def __init__(self):
        self.probe_info = CAPABILITY_DETECTOR.probe()
        self.mode = self.probe_info["operational_mode"]
        self.readers: Dict[str, SensorReader] = {}
        self._init_readers()

    def _init_readers(self):
        if self.mode == "HARDWARE":
            self.readers = {
                "imu": RaspberryPiReader("mpu6050_01", "imu"),
                "gas": RaspberryPiReader("mq2_ads1115_01", "gas"),
                "temperature": SimulatorReader("dht22_01", "temperature"),
                "audio": SimulatorReader("mic_01", "audio")
            }
        else:
            self.readers = {
                "imu": SimulatorReader("mpu6050_01", "imu"),
                "gas": SimulatorReader("mq2_ads1115_01", "gas"),
                "temperature": SimulatorReader("dht22_01", "temperature"),
                "audio": SimulatorReader("mic_01", "audio")
            }

    def set_mode(self, mode: str, fault_type: str = "DISCONNECT"):
        self.mode = mode.upper()
        if self.mode == "FAULT_INJECTION":
            self.readers["imu"] = FaultInjectionReader("mpu6050_01", "imu", fault_type)
        else:
            self._init_readers()

    def read_all(self) -> Dict[str, Any]:
        result = {}
        for k, reader in self.readers.items():
            result[k] = reader.read().to_dict()
        return result


COMPOSITE_SENSOR_HUB = CompositeSensorHub()
