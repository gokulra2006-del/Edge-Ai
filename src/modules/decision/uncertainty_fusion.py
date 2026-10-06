"""Uncertainty-Aware Fusion Engine (Phase 6B).

Implements explicit, logged multi-factor risk computation:
final_risk = event_confidence x temporal_consistency x sensor_agreement
             x device_health x calibration_quality x penalties

Features:
- Configurable factor sets for systematic ablation testing.
- Strict monotonic non-increasing property on sensor/health degradation.
- Safety guard: low risk with high raw evidence routes to REVIEW_REQUIRED instead of silent drop.
- Full factor breakdown logged with every decision.
"""
from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

DecisionAction = Literal["DISPATCH_ALERT", "REVIEW_REQUIRED", "SUPPRESS_NOISE"]


@dataclass
class RiskFactors:
    event_confidence: float
    temporal_consistency: float
    sensor_agreement: float
    device_health: float
    calibration_quality: float
    ood_penalty: float = 1.0
    evidence_duration_penalty: float = 1.0
    zone_reliability_penalty: float = 1.0

    def compute_final_risk(self, enabled_factors: Optional[Set[str]] = None) -> float:
        """
        Computes final risk in [0.0, 1.0].
        If enabled_factors is provided, only specified factors contribute (others default to 1.0).
        """
        active = enabled_factors if enabled_factors is not None else {
            "temporal_consistency",
            "sensor_agreement",
            "device_health",
            "calibration_quality",
            "penalties",
        }

        risk = max(0.0, min(1.0, self.event_confidence))

        if "temporal_consistency" in active:
            risk *= max(0.0, min(1.0, self.temporal_consistency))
        if "sensor_agreement" in active:
            risk *= max(0.0, min(1.0, self.sensor_agreement))
        if "device_health" in active:
            risk *= max(0.0, min(1.0, self.device_health))
        if "calibration_quality" in active:
            risk *= max(0.0, min(1.0, self.calibration_quality))

        if "penalties" in active:
            risk *= max(0.1, min(1.0, self.ood_penalty))
            risk *= max(0.1, min(1.0, self.evidence_duration_penalty))
            risk *= max(0.1, min(1.0, self.zone_reliability_penalty))

        return round(max(0.0, min(1.0, risk)), 4)

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class UncertaintyDecision:
    predicted_class: str
    raw_confidence: float
    final_risk: float
    action: DecisionAction
    factors: RiskFactors
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "predicted_class": self.predicted_class,
            "raw_confidence": self.raw_confidence,
            "final_risk": self.final_risk,
            "action": self.action,
            "factors": self.factors.to_dict(),
            "reason": self.reason,
            "metadata": self.metadata,
        }


class UncertaintyAwareFusion:
    """Computes explicit, auditable uncertainty-aware risk scores across edge sensors."""

    def __init__(
        self,
        alert_threshold: float = 0.50,
        strong_evidence_threshold: float = 0.65,
        target_window_steps: int = 5,
        enabled_factors: Optional[Set[str]] = None,
    ):
        self.alert_threshold = alert_threshold
        self.strong_evidence_threshold = strong_evidence_threshold
        self.target_window_steps = target_window_steps
        self.enabled_factors = enabled_factors

    def evaluate(
        self,
        predicted_class: str,
        raw_confidence: float,
        window_history: List[str],
        active_sensor_classes: Dict[str, str],
        device_health_inputs: Dict[str, float],
        is_ood: bool = False,
        evidence_duration_sec: float = 2.0,
        zone_reliability: float = 1.0,
        calibration_quality: float = 1.0,
    ) -> UncertaintyDecision:
        """
        Evaluates full multi-factor uncertainty risk.
        """
        # 1. Temporal consistency
        temporal = self.compute_temporal_consistency(predicted_class, window_history)

        # 2. Sensor agreement
        agreement = self.compute_sensor_agreement(predicted_class, active_sensor_classes)

        # 3. Device health
        health = self.compute_device_health(device_health_inputs)

        # 4. Calibration quality
        calib = max(0.0, min(1.0, calibration_quality))

        # 5. Penalties
        ood_pen = 0.60 if is_ood else 1.0
        dur_pen = 0.75 if evidence_duration_sec < 1.0 else 1.0
        zone_pen = 0.85 if zone_reliability < 0.70 else 1.0

        factors = RiskFactors(
            event_confidence=round(max(0.0, min(1.0, raw_confidence)), 4),
            temporal_consistency=round(temporal, 4),
            sensor_agreement=round(agreement, 4),
            device_health=round(health, 4),
            calibration_quality=round(calib, 4),
            ood_penalty=round(ood_pen, 4),
            evidence_duration_penalty=round(dur_pen, 4),
            zone_reliability_penalty=round(zone_pen, 4),
        )

        final_risk = factors.compute_final_risk(self.enabled_factors)

        # Safety Guard Decision Logic
        if predicted_class == "NORMAL":
            action: DecisionAction = "SUPPRESS_NOISE"
            reason = "Nominal state classification"
        elif final_risk >= self.alert_threshold:
            action = "DISPATCH_ALERT"
            reason = f"High-confidence verified event (risk={final_risk:.2f} >= {self.alert_threshold:.2f})"
        elif raw_confidence >= self.strong_evidence_threshold:
            # SAFETY GUARD: Raw evidence was strong, but risk was attenuated by uncertainty/health.
            # Route to human review instead of silently dropping the potential incident.
            action = "REVIEW_REQUIRED"
            reason = (
                f"Safety guard triggered: raw confidence ({raw_confidence:.2f}) exceeds threshold, "
                f"but uncertainty factors attenuated risk to {final_risk:.2f}. Human review required."
            )
        else:
            action = "SUPPRESS_NOISE"
            reason = f"Low risk ({final_risk:.2f} < {self.alert_threshold:.2f}) suppressed as noise"

        return UncertaintyDecision(
            predicted_class=predicted_class,
            raw_confidence=round(raw_confidence, 4),
            final_risk=final_risk,
            action=action,
            factors=factors,
            reason=reason,
            metadata={
                "is_ood": is_ood,
                "evidence_duration_sec": evidence_duration_sec,
                "enabled_factors": list(self.enabled_factors) if self.enabled_factors else "all",
            },
        )

    def compute_temporal_consistency(self, target_class: str, history: List[str]) -> float:
        """
        Ratio of window frames matching target_class scaled by window saturation factor.
        """
        if not history:
            return 0.50
        n_match = sum(1 for c in history if c == target_class)
        ratio = n_match / len(history)
        saturation = min(1.0, len(history) / self.target_window_steps)
        return round(ratio * saturation, 4)

    def compute_sensor_agreement(self, target_class: str, sensor_classes: Dict[str, str]) -> float:
        """
        Cross-modal agreement score:
        - 1.0 if all active sensors agree on target_class.
        - Proportionate fraction if partial agreement.
        - Drops to 0.30 if conflicting emergency classes are reported.
        """
        if not sensor_classes:
            return 0.50

        total_sensors = len(sensor_classes)
        matches = sum(1 for c in sensor_classes.values() if c == target_class)

        # Check for active conflicting non-normal classes
        non_normal_classes = {c for c in sensor_classes.values() if c != "NORMAL"}
        if len(non_normal_classes) > 1:
            return 0.30  # Strong disagreement penalty

        return round(matches / total_sensors, 4)

    def compute_device_health(self, health_inputs: Dict[str, float]) -> float:
        """
        Computes composite device health score from:
        - camera: 0.40 weight
        - audio: 0.40 weight
        - sensors: 0.20 weight
        """
        w_cam = 0.40
        w_aud = 0.40
        w_sens = 0.20

        cam_score = max(0.0, min(1.0, health_inputs.get("camera", 1.0)))
        aud_score = max(0.0, min(1.0, health_inputs.get("audio", 1.0)))
        sens_score = max(0.0, min(1.0, health_inputs.get("sensors", 1.0)))

        score = (w_cam * cam_score) + (w_aud * aud_score) + (w_sens * sens_score)
        return round(score, 4)
