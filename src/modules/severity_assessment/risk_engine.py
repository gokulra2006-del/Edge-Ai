"""Configurable 0-100 risk assessment with explicit uncertainty."""
from __future__ import annotations
from typing import Any, Dict

class RiskEngine:
    def __init__(self, config: Dict[str, Any]): self.config = config
    def assess(self, fusion: Dict[str, Any], temporal: Dict[str, Any], zone: str = "ZONE_B_INTERSECTION") -> Dict[str, Any]:
        c, w = self.config, self.config["risk"]["weights"]
        multiplier = c["zones"].get(zone, c["zones"]["ZONE_B_INTERSECTION"])["risk_multiplier"]
        factors = {"fusion": fusion["fusion_confidence"], "persistence": temporal["persistence_ratio"], "reliability": fusion["model_reliability"], "modalities": min(1, len(fusion["contributing_modalities"])/2), "zone": min(1, multiplier/1.35)}
        score = round(min(100, sum(w[k]*factors[k] for k in w)*100*multiplier), 1)
        severity = "NORMAL"
        for name, threshold in c["risk"]["thresholds"].items():
            if score >= threshold: severity = name
        reason = "multi-modal persistent evidence" if len(fusion["contributing_modalities"]) >= 2 else "single-modality evidence requires review"
        return {"risk_score": score, "severity": severity, "factors": factors, "explanation": f"{fusion['incident_type']} risk is {score}/100: {reason}.", "escalation_reason": reason}
