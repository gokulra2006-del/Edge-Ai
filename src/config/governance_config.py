"""Typed, validated access to governance settings in advanced_platform.json."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


DEFAULT_USAGE_RESTRICTION = (
    "RESEARCH_ONLY: synthetic-trained models require real-world validation "
    "and operator confirmation."
)


@dataclass(frozen=True)
class GovernanceConfig:
    merge_window_seconds: int = 120
    writer_queue_size: int = 256
    evidence_root: str = "data/evidence"
    usage_restriction: str = DEFAULT_USAGE_RESTRICTION


def _positive_int(value: Any, name: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"governance.{name} must be a positive integer")
    return value


def load_governance_config(path: Path | None = None) -> GovernanceConfig:
    """Load governance settings from the project's established JSON config.

    Missing governance settings use safe defaults. Present invalid values fail
    loudly so a production node is never silently misconfigured.
    """
    config_path = path or Path(__file__).resolve().parent / "advanced_platform.json"
    try:
        document = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Missing platform configuration: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in platform configuration: {config_path}") from exc
    if not isinstance(document, dict):
        raise ValueError("Platform configuration must contain a JSON object")
    settings = document.get("governance", {})
    if not isinstance(settings, dict):
        raise ValueError("governance must contain a JSON object")
    evidence_root = settings.get("evidence_root", "data/evidence")
    restriction = settings.get("usage_restriction", DEFAULT_USAGE_RESTRICTION)
    if not isinstance(evidence_root, str) or not evidence_root.strip():
        raise ValueError("governance.evidence_root must be a non-empty string")
    if not isinstance(restriction, str) or not restriction.strip():
        raise ValueError("governance.usage_restriction must be a non-empty string")
    return GovernanceConfig(
        merge_window_seconds=_positive_int(settings.get("merge_window_seconds"), "merge_window_seconds", 120),
        writer_queue_size=_positive_int(settings.get("writer_queue_size"), "writer_queue_size", 256),
        evidence_root=evidence_root,
        usage_restriction=restriction,
    )
