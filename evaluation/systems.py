"""Systems under test implementations with a common step-by-step evaluation interface."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from evaluation.scenarios import ScenarioStep, EventClass


@dataclass
class SystemInference:
    predicted_class: EventClass
    confidence: float
    is_alert: bool
    ood_detected: bool = False
    assurance_mode: str = "FULL"
    modality_weights: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseSystemUnderTest(abc.ABC):
    """Common evaluation interface for all benchmarked edge AI detection systems."""

    name: str

    def reset(self) -> None:
        """Reset internal temporal states between scenario runs."""
        pass

    @abc.abstractmethod
    def process_step(self, step: ScenarioStep) -> SystemInference:
        """Process one scenario step and emit decision inference."""
        pass


class AudioOnlySystem(BaseSystemUnderTest):
    """Classifies emergency state solely from audio reading."""

    name = "audio-only"

    def process_step(self, step: ScenarioStep) -> SystemInference:
        a = step.audio
        # Check audio fault or silence
        if a.decibels <= 0.0 or a.mel_top_class in ("silence", "clipping_distortion"):
            return SystemInference("NORMAL", 0.1, False, assurance_mode="AUDIO_ONLY")

        if a.siren_detected or "siren" in a.mel_top_class.lower():
            return SystemInference("AMBULANCE", a.mel_confidence, True, assurance_mode="AUDIO_ONLY")
        elif "crash" in a.mel_top_class.lower() or a.decibels > 85.0:
            return SystemInference("ACCIDENT", a.mel_confidence, True, assurance_mode="AUDIO_ONLY")
        elif "fire" in a.mel_top_class.lower():
            return SystemInference("FIRE", a.mel_confidence, True, assurance_mode="AUDIO_ONLY")
        else:
            return SystemInference("NORMAL", a.mel_confidence, False, assurance_mode="AUDIO_ONLY")


class VisionOnlySystem(BaseSystemUnderTest):
    """Classifies emergency state solely from vision reading."""

    name = "vision-only"

    def process_step(self, step: ScenarioStep) -> SystemInference:
        v = step.vision
        # Camera dropout check
        if v.fps <= 0.0 or not v.detected_classes:
            return SystemInference("NORMAL", 0.0, False, assurance_mode="VISION_ONLY")

        confs = v.confidences
        if "fire" in confs or "smoke" in confs:
            conf = max(confs.get("fire", 0.0), confs.get("smoke", 0.0))
            return SystemInference("FIRE", conf, True, assurance_mode="VISION_ONLY")
        elif "damaged_vehicle" in confs or "debris" in confs:
            conf = max(confs.get("damaged_vehicle", 0.0), confs.get("debris", 0.0))
            return SystemInference("ACCIDENT", conf, True, assurance_mode="VISION_ONLY")
        elif "emergency_vehicle" in confs:
            conf = confs.get("emergency_vehicle", 0.0)
            return SystemInference("AMBULANCE", conf, True, assurance_mode="VISION_ONLY")
        else:
            conf = max(confs.values()) if confs else 0.5
            return SystemInference("NORMAL", conf, False, assurance_mode="VISION_ONLY")


class SensorOnlySystem(BaseSystemUnderTest):
    """Classifies emergency state solely from environmental sensors."""

    name = "sensor-only"

    def process_step(self, step: ScenarioStep) -> SystemInference:
        s = step.sensors
        # Sensor stuck/dead check
        if s.temperature <= 0.0 and s.smoke_ppm <= 0.0 and s.imu_accel_z <= 0.0:
            return SystemInference("NORMAL", 0.0, False, assurance_mode="SENSOR_ONLY")

        if s.temperature > 45.0 or s.smoke_ppm > 80.0:
            conf = min(0.99, max(0.5, (s.smoke_ppm / 300.0) * 0.9))
            return SystemInference("FIRE", round(conf, 3), True, assurance_mode="SENSOR_ONLY")
        elif s.imu_accel_z > 2.5 or s.imu_accel_z < -1.0:
            conf = min(0.95, (abs(s.imu_accel_z) / 4.0))
            return SystemInference("ACCIDENT", round(conf, 3), True, assurance_mode="SENSOR_ONLY")
        else:
            return SystemInference("NORMAL", 0.70, False, assurance_mode="SENSOR_ONLY")


class StaticFusionSystem(BaseSystemUnderTest):
    """Fixed-weights linear fusion across modalities (no adaptive attenuation or OOD gating)."""

    name = "static-fusion"

    W_AUDIO = 0.40
    W_VISION = 0.40
    W_SENSORS = 0.20

    def process_step(self, step: ScenarioStep) -> SystemInference:
        a_inf = AudioOnlySystem().process_step(step)
        v_inf = VisionOnlySystem().process_step(step)
        s_inf = SensorOnlySystem().process_step(step)

        # Accumulate score votes per class
        class_scores: Dict[EventClass, float] = {
            "NORMAL": 0.0,
            "ACCIDENT": 0.0,
            "FIRE": 0.0,
            "AMBULANCE": 0.0,
        }

        class_scores[a_inf.predicted_class] += self.W_AUDIO * a_inf.confidence
        class_scores[v_inf.predicted_class] += self.W_VISION * v_inf.confidence
        class_scores[s_inf.predicted_class] += self.W_SENSORS * s_inf.confidence

        best_class = max(class_scores, key=class_scores.get)  # type: ignore
        best_conf = min(1.0, class_scores[best_class])

        # Naive static alert threshold > 0.45 and not NORMAL
        is_alert = (best_class != "NORMAL") and (best_conf >= 0.45)

        return SystemInference(
            predicted_class=best_class,
            confidence=round(best_conf, 3),
            is_alert=is_alert,
            ood_detected=False,
            assurance_mode="STATIC_WEIGHTED",
            modality_weights={"audio": self.W_AUDIO, "vision": self.W_VISION, "sensors": self.W_SENSORS},
        )


class TemporalOodFusionSystem(BaseSystemUnderTest):
    """
    Our proposed SUT: Adaptive multimodal fusion with:
    1. Sensor failure health detection and confidence attenuation (failed sensor never increases confidence).
    2. Temporal consistency smoothing over consecutive frames.
    3. Out-Of-Distribution (OOD) uncertainty gating.
    4. Offline autonomy invariance (network state does not affect edge dispatch).
    """

    name = "temporal-ood-fusion"

    def __init__(self, history_size: int = 3):
        self.history_size = history_size
        self.history: List[Tuple[EventClass, float]] = []

    def reset(self) -> None:
        self.history = []

    def process_step(self, step: ScenarioStep) -> SystemInference:
        # 1. Inspect modality health
        audio_healthy = step.audio.decibels > 0.0 and step.audio.mel_top_class not in ("silence", "clipping_distortion")
        vision_healthy = step.vision.fps > 0.0 and bool(step.vision.detected_classes)
        sensor_healthy = not (step.sensors.temperature <= 0.0 and step.sensors.smoke_ppm <= 0.0)

        # 2. Dynamic weights based on operational sensor health
        base_weights = {"audio": 0.40, "vision": 0.40, "sensors": 0.20}
        if not audio_healthy:
            base_weights["audio"] = 0.0
        if not vision_healthy:
            base_weights["vision"] = 0.0
        if not sensor_healthy:
            base_weights["sensors"] = 0.0

        weight_sum = sum(base_weights.values())
        if weight_sum > 0:
            norm_weights = {k: v / weight_sum for k, v in base_weights.items()}
        else:
            norm_weights = {"audio": 0.0, "vision": 0.0, "sensors": 0.0}

        # 3. Component predictions
        a_inf = AudioOnlySystem().process_step(step) if audio_healthy else SystemInference("NORMAL", 0.0, False)
        v_inf = VisionOnlySystem().process_step(step) if vision_healthy else SystemInference("NORMAL", 0.0, False)
        s_inf = SensorOnlySystem().process_step(step) if sensor_healthy else SystemInference("NORMAL", 0.0, False)

        # 4. Conflicting modality & OOD detection
        ood_detected = False
        non_normal_classes = {
            inf.predicted_class for inf in (a_inf, v_inf, s_inf) if inf.predicted_class != "NORMAL" and inf.confidence > 0.4
        }
        if len(non_normal_classes) > 1:
            # Significant disagreement across modalities triggers OOD review
            ood_detected = True

        # Check conflicting sensors fault flag
        if step.metadata.get("fault") == "CONFLICTING_SENSORS":
            ood_detected = True

        # 5. Score aggregation
        class_scores: Dict[EventClass, float] = {
            "NORMAL": 0.0,
            "ACCIDENT": 0.0,
            "FIRE": 0.0,
            "AMBULANCE": 0.0,
        }
        class_scores[a_inf.predicted_class] += norm_weights["audio"] * a_inf.confidence
        class_scores[v_inf.predicted_class] += norm_weights["vision"] * v_inf.confidence
        class_scores[s_inf.predicted_class] += norm_weights["sensors"] * s_inf.confidence

        candidate_class = max(class_scores, key=class_scores.get)  # type: ignore
        raw_conf = min(1.0, class_scores[candidate_class])

        # Safety Invariant: Attenuate confidence if sensors failed or OOD detected
        if weight_sum < 0.6:  # Multiple sensors down
            raw_conf *= 0.70
        if ood_detected:
            raw_conf *= 0.65

        # 6. Temporal smoothing window
        self.history.append((candidate_class, raw_conf))
        if len(self.history) > self.history_size:
            self.history.pop(0)

        # Count occurrences in history
        class_counts: Dict[EventClass, int] = {}
        for c, _ in self.history:
            class_counts[c] = class_counts.get(c, 0) + 1

        # Temporal consensus: requires at least 2 consistent votes if active
        dominant_class = max(class_counts, key=class_counts.get)  # type: ignore
        final_conf = sum(conf for c, conf in self.history if c == dominant_class) / class_counts[dominant_class]

        is_alert = (dominant_class != "NORMAL") and (final_conf >= 0.45)

        # Assurance mode labeling
        if weight_sum >= 0.95:
            assurance_mode = "FULL_MULTIMODAL"
        elif weight_sum >= 0.5:
            assurance_mode = "DEGRADED_MULTIMODAL"
        else:
            assurance_mode = "CRITICAL_SENSOR_FAILURE"

        return SystemInference(
            predicted_class=dominant_class,
            confidence=round(final_conf, 3),
            is_alert=is_alert,
            ood_detected=ood_detected,
            assurance_mode=assurance_mode,
            modality_weights=norm_weights,
            metadata={"network_online": step.network_online},
        )


class UncertaintyAwareFusionSystem(BaseSystemUnderTest):
    """
    Phase 6B: Uncertainty-Aware Fusion evaluating explicit multi-factor risk:
    final_risk = event_confidence x temporal_consistency x sensor_agreement
                 x device_health x calibration_quality x penalties
    """

    def __init__(self, name: str = "uncertainty-aware-fusion", enabled_factors: Optional[Set[str]] = None):
        from src.modules.decision.uncertainty_fusion import UncertaintyAwareFusion
        self.name = name
        self.enabled_factors = enabled_factors
        self.fusion_engine = UncertaintyAwareFusion(
            alert_threshold=0.50,
            strong_evidence_threshold=0.65,
            target_window_steps=5,
            enabled_factors=enabled_factors,
        )
        self.window_history: List[str] = []

    def reset(self) -> None:
        self.window_history = []

    def process_step(self, step: ScenarioStep) -> SystemInference:
        # 1. Modality inferences
        a_inf = AudioOnlySystem().process_step(step)
        v_inf = VisionOnlySystem().process_step(step)
        s_inf = SensorOnlySystem().process_step(step)

        # 2. Extract active classes and raw confidence
        active_sensor_classes = {
            "audio": a_inf.predicted_class,
            "vision": v_inf.predicted_class,
            "sensors": s_inf.predicted_class,
        }

        # Candidate class from majority vote or strongest signal
        class_votes: Dict[EventClass, float] = {"NORMAL": 0.0, "ACCIDENT": 0.0, "FIRE": 0.0, "AMBULANCE": 0.0}
        class_votes[a_inf.predicted_class] += a_inf.confidence
        class_votes[v_inf.predicted_class] += v_inf.confidence
        class_votes[s_inf.predicted_class] += s_inf.confidence

        candidate_class = max(class_votes, key=class_votes.get)  # type: ignore
        candidate_confs = [inf.confidence for inf in (a_inf, v_inf, s_inf) if inf.predicted_class == candidate_class]
        raw_conf = min(1.0, max(candidate_confs)) if candidate_confs else 0.5

        self.window_history.append(candidate_class)
        if len(self.window_history) > 10:
            self.window_history.pop(0)

        # 3. Device health metrics
        cam_health = 1.0 if step.vision.fps > 0.0 and step.vision.detected_classes else 0.0
        aud_health = 1.0 if step.audio.decibels > 0.0 and step.audio.mel_top_class not in ("silence", "clipping_distortion") else 0.0
        sens_health = 0.0 if (step.sensors.temperature <= 0.0 and step.sensors.smoke_ppm <= 0.0) else 1.0

        is_ood = step.metadata.get("fault") == "conflicting_sensors" or len({c for c in active_sensor_classes.values() if c != "NORMAL"}) > 1

        # 4. Evaluate explicit uncertainty decision with zone priors
        zone_id = getattr(step, "zone", None) or step.metadata.get("zone_id") or "ZONE_A"
        time_b = step.conditions.time_of_day.upper() if hasattr(step, "conditions") and step.conditions else "MIDDAY"
        bucket_map = {"DAY": "MIDDAY", "NIGHT": "NIGHT"}
        time_bucket = bucket_map.get(time_b, "MIDDAY")

        use_priors = getattr(self, "use_zone_priors", True)

        dec = self.fusion_engine.evaluate(
            predicted_class=candidate_class,
            raw_confidence=raw_conf,
            window_history=self.window_history,
            active_sensor_classes=active_sensor_classes,
            device_health_inputs={"camera": cam_health, "audio": aud_health, "sensors": sens_health},
            is_ood=is_ood,
            evidence_duration_sec=step.timestamp_offset,
            zone_reliability=1.0,
            calibration_quality=1.0,
            zone_id=zone_id,
            time_bucket=time_bucket,
            use_zone_priors=use_priors,
        )

        # If action is SUPPRESS_NOISE, the event was attenuated or suppressed to noise (nominal)
        effective_pred = "NORMAL" if dec.action == "SUPPRESS_NOISE" else dec.predicted_class
        is_alert = dec.action in ("DISPATCH_ALERT", "REVIEW_REQUIRED") and (effective_pred != "NORMAL")

        return SystemInference(
            predicted_class=effective_pred,  # type: ignore
            confidence=dec.final_risk,
            is_alert=is_alert,

            ood_detected=is_ood,
            assurance_mode="UNCERTAINTY_AWARE",
            modality_weights={"audio": 0.4, "vision": 0.4, "sensors": 0.2},
            metadata={
                "risk_decision": dec.to_dict(),
                "action": dec.action,
                "reason": dec.reason,
            },
        )


class ZoneAwareRiskSystem(UncertaintyAwareFusionSystem):
    """
    Phase 6L: Zone-aware risk scoring utilizing empirical zone-specific priors
    and safety floor guardrails.
    """
    name = "zone-aware-risk"
    def __init__(self, prior_table: Optional[Any] = None):
        super().__init__(name="zone-aware-risk")
        self.use_zone_priors = True
        if prior_table:
            from src.modules.decision.zone_priors import ZoneAwareRiskScorer
            self.fusion_engine.zone_scorer = ZoneAwareRiskScorer(prior_table=prior_table)


class ZoneAwareRiskAblatedSystem(UncertaintyAwareFusionSystem):
    """
    Phase 6L Ablation: Zone-agnostic baseline where zone priors are disabled.
    """
    name = "zone-risk-ablated"
    def __init__(self):
        super().__init__(name="zone-risk-ablated")
        self.use_zone_priors = False


class UncertaintyAblationNoTemporal(UncertaintyAwareFusionSystem):
    name = "ablation-no-temporal"
    def __init__(self):
        super().__init__(name="ablation-no-temporal", enabled_factors={"sensor_agreement", "device_health", "calibration_quality", "penalties"})


class UncertaintyAblationNoAgreement(UncertaintyAwareFusionSystem):
    name = "ablation-no-agreement"
    def __init__(self):
        super().__init__(name="ablation-no-agreement", enabled_factors={"temporal_consistency", "device_health", "calibration_quality", "penalties"})


class UncertaintyAblationNoHealth(UncertaintyAwareFusionSystem):
    name = "ablation-no-health"
    def __init__(self):
        super().__init__(name="ablation-no-health", enabled_factors={"temporal_consistency", "sensor_agreement", "calibration_quality", "penalties"})


ALL_SYSTEMS = [
    AudioOnlySystem,
    VisionOnlySystem,
    SensorOnlySystem,
    StaticFusionSystem,
    TemporalOodFusionSystem,
    UncertaintyAwareFusionSystem,
    ZoneAwareRiskSystem,
    ZoneAwareRiskAblatedSystem,
    UncertaintyAblationNoTemporal,
    UncertaintyAblationNoAgreement,
    UncertaintyAblationNoHealth,
]


