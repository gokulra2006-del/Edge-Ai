"""Expose measured model limits beside live predictions without changing actuation rules."""
import json
from pathlib import Path
from typing import Any, Dict, Optional

from src.config.model_profile import model_profile


ROOT = Path(__file__).resolve().parents[3]
SYNTHETIC_DIR = ROOT / "models" / "new_dataset"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _metric(report: Dict[str, Any], label: str) -> Optional[float]:
    value = report.get(label, {})
    if isinstance(value, dict):
        value = value.get("f1-score", value.get("f1"))
    if isinstance(value, (int, float)):
        return float(value)
    # YOLO evaluation reports classes as a list of records rather than a
    # sklearn-style dictionary. Normalize both formats for the dashboard.
    for item in report.get("per_class", []):
        if isinstance(item, dict) and str(item.get("class", "")).lower() == label.lower():
            value = item.get("f1")
            return float(value) if isinstance(value, (int, float)) else None
    return None


class ModelAssuranceService:
    """Turns persisted test metrics into operator-facing evidence limits.

    This layer is deliberately advisory: existing rule thresholds and actuator commands
    remain authoritative. It prevents a dashboard confidence score from being mistaken
    for a field-validation claim.
    """

    def __init__(self, root: Path = SYNTHETIC_DIR):
        self.root = root

    def _reports(self) -> Dict[str, Dict[str, Any]]:
        return {
            "audio": _read_json(self.root / "audio_evaluation.json"),
            "fire_smoke": _read_json(self.root / "fire_smoke_evaluation.json"),
            "vehicle": _read_json(self.root / "vehicle_evaluation.json"),
        }

    @staticmethod
    def _vision_domain(label: str) -> Optional[str]:
        normalized = label.lower()
        if normalized in {"fire", "smoke"}:
            return "fire_smoke"
        if normalized in {"car", "truck", "bus", "motorcycle", "vehicle"}:
            return "vehicle"
        return None

    @staticmethod
    def _readiness(f1: Optional[float]) -> str:
        if f1 is None:
            return "UNMEASURED"
        if f1 < 0.60:
            return "REVIEW_REQUIRED"
        if f1 < 0.80:
            return "CAUTION"
        return "SUPPORTED"

    def summarize(self, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        state = state or {}
        telemetry = state.get("telemetry", state)
        active_event = state.get("active_event", {})
        profile = model_profile()
        audio = telemetry.get("audio_prediction", {})
        vision = telemetry.get("vision_prediction", {})
        reports = self._reports() if profile.get("synthetic") else {}

        audio_label = str(audio.get("class", "unknown")).lower()
        vision_label = str(vision.get("class", "unknown")).lower()
        audio_f1 = _metric(reports.get("audio", {}), audio_label)
        vision_domain = self._vision_domain(vision_label)
        vision_f1 = _metric(reports.get(vision_domain or "", {}), vision_label)

        modalities = [
            {
                "modality": "acoustic",
                "label": audio_label,
                "model_confidence": float(audio.get("confidence", 0.0)),
                "held_out_f1": audio_f1,
                "readiness": self._readiness(audio_f1),
                "source": audio.get("dataset", "Unavailable"),
            },
            {
                "modality": "vision",
                "label": vision_label,
                "model_confidence": float(vision.get("confidence", 0.0)),
                "held_out_f1": vision_f1,
                "readiness": self._readiness(vision_f1),
                "source": vision.get("dataset", "Unavailable"),
            },
        ]
        weakest = next((item for item in modalities if item["readiness"] == "REVIEW_REQUIRED"), None)
        synthetic = bool(profile.get("synthetic"))
        if synthetic:
            status = "RESEARCH_ONLY"
            guidance = "Generated-data profile: confirm with physical sensors and an operator before action."
        elif weakest:
            status = "REVIEW_REQUIRED"
            guidance = f"{weakest['modality'].title()} class '{weakest['label']}' has limited held-out support; request corroboration."
        elif str(active_event.get("event", "NORMAL")).upper() != "NORMAL":
            status = "MULTIMODAL_REVIEW"
            guidance = "Cross-check the evidence chain and operator protocol before escalating the incident."
        else:
            status = "MONITORING"
            guidance = "No unsupported model claim is being used for an active incident."

        return {
            "profile": profile.get("name", "legacy"),
            "synthetic_data": synthetic,
            "status": status,
            "guidance": guidance,
            "operator_confirmation_required": synthetic or status in {"REVIEW_REQUIRED", "MULTIMODAL_REVIEW"},
            "actuation_modified": False,
            "modalities": modalities,
            "event": active_event.get("event", "NORMAL"),
        }


MODEL_ASSURANCE = ModelAssuranceService()
