"""
Module 5: Severity Assessment.
Evaluates event threat level, life-safety risk, and urgency score.
"""
from src.core.data_models import FusedEvent, SeverityAssessment
from src.modules.logging.logger import LOGGER


class SeverityEvaluator:
    def evaluate(self, event: FusedEvent) -> SeverityAssessment:
        etype = event.event_type
        conf = event.confidence
        packet = event.raw_packet

        # --- CRITICAL ---
        if etype == "ACCIDENT" and event.is_verified and conf >= 0.75:
            score = conf * 1.0
            rationale = "Multi-sensor verified road accident with acoustic crash and physical impact evidence."
            level = "CRITICAL"
        elif etype == "FIRE_HAZARD" and packet.environment.temperature_c >= 55.0 and packet.environment.smoke_ppm >= 150.0:
            score = 0.95
            rationale = "Severe fire hazard confirmed by thermal spikes and dense smoke concentration."
            level = "CRITICAL"

        # --- HIGH ---
        elif etype == "EMERGENCY_VEHICLE":
            score = 0.85 * conf
            vehicle_type = packet.audio_prediction.class_name.upper()
            rationale = f"Active emergency responder ({vehicle_type}) approaching intersection. Immediate green priority required."
            level = "HIGH"
        elif etype == "ACCIDENT":
            score = 0.70
            rationale = "Probable collision detected, but awaiting secondary corroboration."
            level = "HIGH"
        elif etype == "FIRE_HAZARD":
            score = 0.75
            rationale = "Visual fire/smoke plume detected in transit corridor."
            level = "HIGH"

        # --- MEDIUM ---
        elif etype == "ROAD_HAZARD":
            score = 0.50
            hazard = packet.vision_prediction.primary_class
            rationale = f"Road hazard identified ({hazard}). Caution advised to avoid vehicle damage."
            level = "MEDIUM"

        # --- LOW ---
        else:
            score = 0.10
            rationale = "Normal traffic operations within standard parameters."
            level = "LOW"

        assessment = SeverityAssessment(
            level=level,
            score=round(score, 3),
            rationale=rationale
        )
        LOGGER.info(f"Severity Evaluated: Level={assessment.level} (Score={assessment.score:.2f}) - {assessment.rationale}")
        return assessment
