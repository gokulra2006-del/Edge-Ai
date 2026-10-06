"""
Config Schema and Startup Validation for Sentinel-AI Production Deployment.
Validates production and runtime configuration structures for type safety,
required sections, valid numerical ranges, and logical threshold order.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


class ConfigValidationError(ValueError):
    """Raised when configuration fails schema or range validation."""
    def __init__(self, errors: List[str]):
        super().__init__("Configuration validation failed:\n  - " + "\n  - ".join(errors))
        self.errors = errors


def validate_config(cfg: Dict[str, Any]) -> List[str]:
    """
    Validates a configuration dictionary against the Sentinel-AI production schema.
    Returns a list of validation error messages (empty list if valid).
    """
    errors: List[str] = []

    if not isinstance(cfg, dict):
        return ["Root configuration must be a JSON object (dictionary)"]

    # 1. Fusion section
    fusion = cfg.get("fusion")
    if not isinstance(fusion, dict):
        errors.append("Missing or invalid 'fusion' section (must be object)")
    else:
        weights = fusion.get("weights")
        if not isinstance(weights, dict):
            errors.append("fusion.weights must be an object")
        else:
            for k in ("audio", "vision", "sensors", "reliability"):
                val = weights.get(k)
                if not isinstance(val, (int, float)) or val < 0.0 or val > 1.0:
                    errors.append(f"fusion.weights.{k} must be a float between 0.0 and 1.0 (got {val})")
        min_mod = fusion.get("minimum_modalities")
        if not isinstance(min_mod, int) or min_mod < 1:
            errors.append(f"fusion.minimum_modalities must be an integer >= 1 (got {min_mod})")

    # 2. Temporal section
    temporal = cfg.get("temporal")
    if not isinstance(temporal, dict):
        errors.append("Missing or invalid 'temporal' section (must be object)")
    else:
        for k in ("window_size", "positive_frames", "consecutive_positive"):
            v = temporal.get(k)
            if not isinstance(v, int) or v < 1:
                errors.append(f"temporal.{k} must be an integer >= 1 (got {v})")
        min_conf = temporal.get("minimum_average_confidence")
        if not isinstance(min_conf, (int, float)) or not (0.0 <= min_conf <= 1.0):
            errors.append(f"temporal.minimum_average_confidence must be in [0.0, 1.0] (got {min_conf})")

    # 3. Risk section
    risk = cfg.get("risk")
    if not isinstance(risk, dict):
        errors.append("Missing or invalid 'risk' section (must be object)")
    else:
        r_weights = risk.get("weights")
        if not isinstance(r_weights, dict):
            errors.append("risk.weights must be an object")
        else:
            for k in ("fusion", "persistence", "reliability", "modalities", "zone"):
                v = r_weights.get(k)
                if not isinstance(v, (int, float)) or v < 0.0 or v > 1.0:
                    errors.append(f"risk.weights.{k} must be in [0.0, 1.0] (got {v})")
        r_thresh = risk.get("thresholds")
        if not isinstance(r_thresh, dict):
            errors.append("risk.thresholds must be an object")
        else:
            for k in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
                v = r_thresh.get(k)
                if not isinstance(v, (int, float)) or v < 0 or v > 100:
                    errors.append(f"risk.thresholds.{k} must be a number in [0, 100] (got {v})")
            if (
                isinstance(r_thresh.get("LOW"), (int, float))
                and isinstance(r_thresh.get("MEDIUM"), (int, float))
                and isinstance(r_thresh.get("HIGH"), (int, float))
                and isinstance(r_thresh.get("CRITICAL"), (int, float))
            ):
                if not (r_thresh["LOW"] < r_thresh["MEDIUM"] < r_thresh["HIGH"] < r_thresh["CRITICAL"]):
                    errors.append(
                        f"risk.thresholds must satisfy LOW < MEDIUM < HIGH < CRITICAL "
                        f"(got {r_thresh['LOW']} < {r_thresh['MEDIUM']} < {r_thresh['HIGH']} < {r_thresh['CRITICAL']})"
                    )

    # 4. Governance section
    gov = cfg.get("governance")
    if not isinstance(gov, dict):
        errors.append("Missing or invalid 'governance' section (must be object)")
    else:
        for k in ("merge_window_seconds", "writer_queue_size"):
            v = gov.get(k)
            if not isinstance(v, int) or v < 1:
                errors.append(f"governance.{k} must be an integer >= 1 (got {v})")
        if not isinstance(gov.get("evidence_root"), str) or not gov.get("evidence_root").strip():
            errors.append("governance.evidence_root must be a non-empty string path")

    # 5. Monitoring section
    monitoring = cfg.get("monitoring")
    if not isinstance(monitoring, dict):
        errors.append("Missing or invalid 'monitoring' section (must be object)")
    else:
        drift = monitoring.get("drift")
        if not isinstance(drift, dict):
            errors.append("monitoring.drift must be an object")
        else:
            for k in ("rolling_window_samples", "minimum_samples_guard", "snapshot_interval_seconds"):
                v = drift.get(k)
                if not isinstance(v, int) or v < 1:
                    errors.append(f"monitoring.drift.{k} must be an integer >= 1 (got {v})")
        health = monitoring.get("health")
        if not isinstance(health, dict):
            errors.append("monitoring.health must be an object")
        else:
            for k in ("poll_interval_seconds", "storage_warning_bytes", "storage_critical_bytes"):
                v = health.get(k)
                if not isinstance(v, (int, float)) or v < 1:
                    errors.append(f"monitoring.health.{k} must be a number >= 1 (got {v})")
            if isinstance(health.get("storage_warning_bytes"), (int, float)) and isinstance(health.get("storage_critical_bytes"), (int, float)):
                if health["storage_critical_bytes"] >= health["storage_warning_bytes"]:
                    errors.append("monitoring.health.storage_critical_bytes must be strictly less than storage_warning_bytes")

        streams = monitoring.get("streams")
        if not isinstance(streams, dict):
            errors.append("monitoring.streams must be an object")
        else:
            cam = streams.get("camera")
            if not isinstance(cam, dict) or not isinstance(cam.get("target_fps"), (int, float)) or cam.get("target_fps") <= 0:
                errors.append("monitoring.streams.camera.target_fps must be positive number")
            audio = streams.get("audio")
            if not isinstance(audio, dict) or not isinstance(audio.get("sample_rate"), int) or audio.get("sample_rate") <= 0:
                errors.append("monitoring.streams.audio.sample_rate must be positive integer")

    # 6. Storage section
    storage = cfg.get("storage")
    if not isinstance(storage, dict):
        errors.append("Missing or invalid 'storage' section (must be object)")
    else:
        ret = storage.get("retention")
        if not isinstance(ret, dict):
            errors.append("storage.retention must be an object")
        else:
            for k in ("raw_telemetry_days", "dvr_max_bytes", "evidence_retention_days"):
                v = ret.get(k)
                if not isinstance(v, (int, float)) or v < 1:
                    errors.append(f"storage.retention.{k} must be a number >= 1 (got {v})")
        wal = storage.get("wal")
        if not isinstance(wal, dict):
            errors.append("storage.wal must be an object")
        else:
            if wal.get("checkpoint_mode") not in ("PASSIVE", "FULL", "RESTART", "TRUNCATE"):
                errors.append(f"storage.wal.checkpoint_mode must be one of PASSIVE, FULL, RESTART, TRUNCATE (got {wal.get('checkpoint_mode')})")

    return errors


def validate_or_raise(cfg: Dict[str, Any]) -> None:
    """Validates configuration, raising ConfigValidationError if invalid."""
    errs = validate_config(cfg)
    if errs:
        raise ConfigValidationError(errs)


def load_and_validate_config(config_path: Path | str) -> Dict[str, Any]:
    """Loads a JSON config file and performs schema and range validation."""
    p = Path(config_path)
    if not p.is_file():
        raise FileNotFoundError(f"Configuration file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigValidationError([f"Malformed JSON in {p}: {exc}"])

    validate_or_raise(data)
    return data
