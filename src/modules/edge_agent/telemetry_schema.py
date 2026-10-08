"""
STAGE I1: Canonical Telemetry Schema 1.0 & Schema Validator.
=============================================================
Strict validation rules:
- schema_version == "1.0"
- device_id, boot_id, event_id, timestamp_utc, clock_status, sequence
- connectivity, data_source ("REAL_HARDWARE" or "SIMULATED")
- sensors, audio_prediction, vision_prediction, health
- No mixing of real and simulated data
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple
import uuid


ClockStatus = Literal["GPS", "NTP", "UNSYNCED"]
ConnectivityStatus = Literal["ONLINE", "OFFLINE", "DEGRADED"]
DataSource = Literal["REAL_HARDWARE", "SIMULATED"]
SensorStatus = Literal["OK", "DEGRADED", "FAILED", "WARMING_UP", "UNAVAILABLE"]
ModelStatus = Literal["PRODUCTION", "CANDIDATE", "RESEARCH_ONLY"]


@dataclass
class TelemetryValidationResult:
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class TelemetryValidator:
    """Validates edge telemetry packets against Schema 1.0."""

    SUPPORTED_MAJOR_VERSION = 1
    ALLOWED_CLOCK_STATUSES = {"GPS", "NTP", "UNSYNCED"}
    ALLOWED_DATA_SOURCES = {"REAL_HARDWARE", "SIMULATED"}
    ALLOWED_SENSOR_STATUSES = {"OK", "DEGRADED", "FAILED", "WARMING_UP", "UNAVAILABLE"}
    ALLOWED_MODEL_STATUSES = {"PRODUCTION", "CANDIDATE", "RESEARCH_ONLY"}

    @classmethod
    def validate(cls, packet: Dict[str, Any]) -> TelemetryValidationResult:
        errors: List[str] = []
        warnings: List[str] = []

        if not isinstance(packet, dict):
            return TelemetryValidationResult(is_valid=False, errors=["Packet must be a JSON object"])

        # 1. Version check
        ver = packet.get("schema_version")
        if not ver or not isinstance(ver, str):
            errors.append("Missing or invalid 'schema_version' (must be string like '1.0')")
        else:
            try:
                major = int(ver.split(".")[0])
                if major != cls.SUPPORTED_MAJOR_VERSION:
                    errors.append(f"Unsupported schema major version '{major}'; expected '{cls.SUPPORTED_MAJOR_VERSION}'")
            except Exception:
                errors.append(f"Malformed 'schema_version': {ver}")

        # 2. Mandatory envelope fields
        for req in ("device_id", "boot_id", "event_id", "timestamp_utc", "clock_status", "sequence", "connectivity", "data_source"):
            if req not in packet:
                errors.append(f"Missing required envelope field '{req}'")

        if packet.get("clock_status") not in cls.ALLOWED_CLOCK_STATUSES:
            errors.append(f"Invalid clock_status '{packet.get('clock_status')}'; allowed: {sorted(cls.ALLOWED_CLOCK_STATUSES)}")

        if packet.get("data_source") not in cls.ALLOWED_DATA_SOURCES:
            errors.append(f"Invalid data_source '{packet.get('data_source')}'; allowed: {sorted(cls.ALLOWED_DATA_SOURCES)}")

        seq = packet.get("sequence")
        if not isinstance(seq, int) or seq < 0:
            errors.append("'sequence' must be a non-negative integer")

        # 3. Subsystem objects
        for sub in ("sensors", "audio_prediction", "vision_prediction", "health"):
            if sub not in packet or not isinstance(packet.get(sub), dict):
                errors.append(f"Missing or non-object field '{sub}'")

        # 4. Sensor validations if present
        sensors = packet.get("sensors")
        if isinstance(sensors, dict):
            gps = sensors.get("gps")
            if not isinstance(gps, dict):
                errors.append("sensors.gps must be an object with latitude, longitude, speed_kmh, fix_valid")
            else:
                for k in ("latitude", "longitude", "speed_kmh", "fix_valid"):
                    if k not in gps:
                        errors.append(f"Missing gps field '{k}'")

        # 5. Audio prediction validation
        audio = packet.get("audio_prediction")
        if isinstance(audio, dict):
            for k in ("class", "confidence", "model_id", "model_version", "model_status", "latency_ms"):
                if k not in audio:
                    errors.append(f"Missing audio_prediction field '{k}'")
            if audio.get("model_status") not in cls.ALLOWED_MODEL_STATUSES:
                errors.append(f"Invalid audio model_status '{audio.get('model_status')}'")

        # 6. Vision prediction validation
        vision = packet.get("vision_prediction")
        if isinstance(vision, dict):
            for k in ("classes", "confidence", "model_id", "model_version", "model_status"):
                if k not in vision:
                    errors.append(f"Missing vision_prediction field '{k}'")

        # 7. Health object validation
        health = packet.get("health")
        if isinstance(health, dict):
            for k in ("cpu_percent", "memory_percent", "temperature_c", "sensor_status", "model_status"):
                if k not in health:
                    errors.append(f"Missing health field '{k}'")

        return TelemetryValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)
