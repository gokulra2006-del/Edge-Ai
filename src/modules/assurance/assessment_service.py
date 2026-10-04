"""Composes assurance, fusion, temporal validation and risk without altering actuators."""
import json
from pathlib import Path
from typing import Any, Dict
from src.modules.assurance.model_assurance import MODEL_ASSURANCE
from src.modules.sensor_fusion.advanced_fusion import AdvancedFusionEngine
from src.modules.sensor_fusion.event_validation import EventValidator
from src.modules.severity_assessment.risk_engine import RiskEngine

CONFIG = json.loads((Path(__file__).resolve().parents[2] / "config" / "advanced_platform.json").read_text())
VALIDATOR = EventValidator(CONFIG)

def assess_live_state(state: Dict[str, Any]) -> Dict[str, Any]:
    assurance = state.get("assurance") or MODEL_ASSURANCE.summarize(state)
    telemetry, active = state.get("telemetry", {}), state.get("active_event", {})
    fusion = AdvancedFusionEngine(CONFIG).fuse(telemetry, assurance)
    temporal = VALIDATOR.ingest(fusion["incident_type"], fusion["fusion_confidence"])
    risk = RiskEngine(CONFIG).assess(fusion, temporal, active.get("zone", "ZONE_B_INTERSECTION"))
    return {"fusion": fusion, "temporal": temporal, "risk": risk, "operator_confirmation_required": assurance.get("operator_confirmation_required", True), "actuation_modified": False}
