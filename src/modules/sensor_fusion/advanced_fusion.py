"""Reliability-aware, configurable evidence fusion for decision support."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List


READINESS = {"SUPPORTED": 1.0, "CAUTION": .72, "REVIEW_REQUIRED": .45, "UNMEASURED": .35}


class AdvancedFusionEngine:
    def __init__(self, config: Dict[str, Any]):
        self.config = config["fusion"]

    def fuse(self, telemetry: Dict[str, Any], assurance: Dict[str, Any]) -> Dict[str, Any]:
        audio, vision = telemetry.get("audio_prediction", {}), telemetry.get("vision_prediction", {})
        env = {"smoke": float(telemetry.get("smoke_level", 0))/120, "temperature": float(telemetry.get("temperature", 0))/70,
               "impact": 1.0 if telemetry.get("impact_detected") else min(1.0, float(telemetry.get("acceleration_g", 0))/3)}
        candidates = {"vehicle_accident": audio.get("confidence", 0) if audio.get("class") == "crash" else 0,
                      "fire_hazard": vision.get("confidence", 0) if vision.get("class") in ("fire", "smoke") else 0,
                      "emergency_vehicle": audio.get("confidence", 0) if audio.get("class") == "siren" else 0}
        event, primary = max(candidates.items(), key=lambda item: item[1])
        evidence = {"audio": float(audio.get("confidence", 0)) if primary else 0, "vision": float(vision.get("confidence", 0)),
                    "sensors": max(0.0, min(1.0, max(env.values())))}
        modalities = [name for name, value in evidence.items() if value >= .5]
        reliability = [READINESS.get(item.get("readiness"), .35) for item in assurance.get("modalities", [])]
        r = sum(reliability)/len(reliability) if reliability else .35
        weights = self.config["weights"]
        confidence = sum(weights[k] * (evidence[k] if k != "reliability" else r) for k in weights)
        if len(modalities) < self.config["minimum_modalities"]: confidence *= .72
        contradiction = ["single-modality evidence" ] if len(modalities) < 2 else []
        return {"incident_type": event if primary >= .4 else "NORMAL", "fusion_confidence": round(min(1, confidence), 4),
                "contributing_modalities": modalities, "individual_confidences": evidence, "model_reliability": round(r, 3),
                "supporting_evidence": [f"{k}: {v:.0%}" for k,v in evidence.items() if v >= .5],
                "contradicting_evidence": contradiction, "timestamp": datetime.now(timezone.utc).isoformat()}
