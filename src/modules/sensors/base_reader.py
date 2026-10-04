"""
Module 1 Hardware Foundation: Unified Sensor Abstraction Layer & Telemetry Contracts.
====================================================================================
Defines abstract base classes, standardized quality metadata, and normalized
reading models for Sentinel-AI sensors across hardware, simulation, and replay modes.
"""
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional


class DriverHealth(str, Enum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    CALIBRATING = "calibrating"
    INVALID = "invalid"
    SIMULATED = "simulated"


@dataclass
class QualityMetadata:
    status: DriverHealth
    confidence: float = 1.0
    latency_ms: float = 0.0
    consecutive_failures: int = 0
    sequence_number: int = 0
    last_calibration_time: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class SensorReading:
    sensor_id: str
    sensor_type: str  # imu, gas, temperature, audio, vision
    timestamp: str
    values: Dict[str, Any]
    quality: QualityMetadata
    source: str = "simulation"  # "raspberry_pi", "simulation", "replay", "fault_injection"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sensor_id": self.sensor_id,
            "sensor_type": self.sensor_type,
            "timestamp": self.timestamp,
            "values": self.values,
            "quality": {
                "status": self.quality.status.value,
                "confidence": round(self.quality.confidence, 3),
                "latency_ms": round(self.quality.latency_ms, 2),
                "consecutive_failures": self.quality.consecutive_failures,
                "sequence_number": self.quality.sequence_number,
                "last_calibration_time": self.quality.last_calibration_time,
                "error_message": self.quality.error_message
            },
            "source": self.source
        }


class SensorReader:
    """Abstract interface for all sensor acquisition drivers."""

    def __init__(self, sensor_id: str, sensor_type: str):
        self.sensor_id = sensor_id
        self.sensor_type = sensor_type
        self.health = DriverHealth.SIMULATED
        self.sequence = 0
        self.consecutive_failures = 0
        self.last_successful_read_time = 0.0

    def read(self) -> SensorReading:
        raise NotImplementedError("SensorReader subclasses must implement read()")

    def calibrate(self, zero_offsets: Optional[Dict[str, float]] = None) -> bool:
        """Runs sensor zero-offset calibration."""
        return True
