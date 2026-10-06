"""
Module: Confidence Reduction on Sensor Failure.
================================================
Attenuates multimodal event confidence and caps permissible system risk scores
when one or more input sensor streams (camera, microphone) experience health
degradation, dropped frames, or hardware disconnection.

Research Hypothesis:
Dynamically attenuating event confidence using sensor health weighting (e.g. 0.5x
for degraded modality, 0.0x for disconnected modality) and capping maximum risk
score to 0.40 under single-sensor operation eliminates 100% of false critical
escalations caused by corrupted or partial hardware feeds.

Primary Metrics:
1. False Critical Escalation Rate: 0% critical alerts triggered when primary sensor
   status is DEGRADED or DOWN.
2. Attenuation Monotonicity: Fused event confidence strictly monotonically decreases
   as sensor error rates or disconnection duration increase.
3. Maximum Risk Cap Enforcement: Hard ceiling enforcement ensuring high raw confidence
   from a degraded stream cannot breach the emergency threshold.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class SensorHealthState:
    sensor_id: str
    modality: str  # CAMERA, AUDIO, RADAR, PIR
    status: str    # HEALTHY, DEGRADED, DOWN
    drop_rate: float = 0.0  # 0.0 to 1.0


@dataclass
class AttenuationResult:
    original_confidence: float
    attenuated_confidence: float
    original_risk_score: float
    attenuated_risk_score: float
    risk_cap_applied: bool
    effective_sensor_weight: float
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_confidence": round(self.original_confidence, 4),
            "attenuated_confidence": round(self.attenuated_confidence, 4),
            "original_risk_score": round(self.original_risk_score, 4),
            "attenuated_risk_score": round(self.attenuated_risk_score, 4),
            "risk_cap_applied": self.risk_cap_applied,
            "effective_sensor_weight": round(self.effective_sensor_weight, 4),
            "reasons": self.reasons,
        }


class SensorConfidenceAttenuator:
    """
    Computes confidence attenuation and safe risk capping based on real-time
    sensor health telemetry.
    """

    HEALTH_WEIGHTS = {
        "HEALTHY": 1.0,
        "DEGRADED": 0.5,
        "DOWN": 0.0,
    }

    # When sensors are compromised, cap the maximum risk score so autonomous
    # actions cannot trigger on dubious hardware inputs.
    DEGRADED_RISK_CAP = 0.45
    DOWN_RISK_CAP = 0.20

    def evaluate_event(
        self,
        primary_modality: str,
        raw_confidence: float,
        raw_risk_score: float,
        sensor_states: List[SensorHealthState],
    ) -> AttenuationResult:
        reasons: List[str] = []
        conf = max(0.0, min(1.0, float(raw_confidence)))
        risk = max(0.0, min(1.0, float(raw_risk_score)))

        # Find matching sensor or default to HEALTHY
        matching_sensors = [s for s in sensor_states if s.modality.upper() == primary_modality.upper()]
        
        if not matching_sensors:
            # Unknown sensor state defaults to degraded safety precaution
            weight = 0.70
            reasons.append(f"SENSOR_UNKNOWN_MODALITY_{primary_modality.upper()}")
            cap = self.DEGRADED_RISK_CAP
        else:
            primary_sensor = matching_sensors[0]
            st = primary_sensor.status.upper()
            base_weight = self.HEALTH_WEIGHTS.get(st, 0.5)

            # Further penalize if drop rate > 0
            drop_penalty = max(0.0, min(1.0, primary_sensor.drop_rate)) * 0.5
            weight = max(0.0, base_weight - drop_penalty)

            if st == "DOWN":
                cap = self.DOWN_RISK_CAP
                reasons.append(f"PRIMARY_SENSOR_DOWN_{primary_sensor.sensor_id}")
            elif st == "DEGRADED":
                cap = self.DEGRADED_RISK_CAP
                reasons.append(f"PRIMARY_SENSOR_DEGRADED_{primary_sensor.sensor_id}")
            else:
                cap = 1.0

            if primary_sensor.drop_rate > 0.10:
                reasons.append(f"HIGH_PACKET_DROP_{primary_sensor.drop_rate*100:.1f}%")

        # Compute attenuated confidence
        attenuated_conf = conf * weight

        # Compute attenuated risk
        attenuated_risk = risk * weight
        risk_capped = False
        if attenuated_risk > cap:
            attenuated_risk = cap
            risk_capped = True
            reasons.append(f"RISK_CEILING_ENFORCED_{cap:.2f}")

        return AttenuationResult(
            original_confidence=conf,
            attenuated_confidence=attenuated_conf,
            original_risk_score=risk,
            attenuated_risk_score=attenuated_risk,
            risk_cap_applied=risk_capped,
            effective_sensor_weight=weight,
            reasons=reasons,
        )
