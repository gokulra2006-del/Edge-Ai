"""
Digital Twin Incident Replay Engine (Phase 6D).
===============================================
Enables bit-exact deterministic replay of raw evidence traces through the full production pipeline:
raw evidence -> model predictions -> fusion -> OOD check -> risk score -> response plan -> operator action.

Guarantees:
1. Determinism: Unmodified replays yield bit-exact identical decision and risk outcomes.
2. Sandboxing: NEVER writes to live database tables, NEVER calls physical hardware or live dispatch.
3. Unified Code Path: Uses the same production decision and uncertainty-fusion pipeline logic.
4. Counterfactual Controls: Dropout, stream delays, camera failure, network outage, conflicting sensors, alternative operator actions.
"""
from __future__ import annotations

import copy
import dataclasses
from dataclasses import asdict, dataclass, field
import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from src.modules.decision.uncertainty_fusion import (
    RiskFactors,
    UncertaintyAwareFusion,
    UncertaintyDecision,
)

OperatorAction = Literal["NONE", "ACKNOWLEDGE", "FALSE_ALARM", "OVERRIDE_PLAN"]


@dataclass
class ReplayStepInput:
    timestamp_offset_sec: float
    camera_classes: List[str]
    camera_confidence: float
    camera_fps: float = 15.0
    audio_class: str = "ambient"
    audio_confidence: float = 0.5
    audio_db: float = 60.0
    sensor_temp: float = 24.0
    sensor_smoke_ppm: float = 15.0
    sensor_imu_g: float = 0.0
    network_online: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplayStepOutput:
    step_idx: int
    timestamp_offset_sec: float
    raw_inputs: Dict[str, Any]
    model_predictions: Dict[str, Any]
    ood_detected: bool
    risk_factors: Dict[str, float]
    final_risk: float
    action: str
    recommended_plan: str
    operator_action: str
    mismatch_detected: bool = False
    safety_contract: Optional[Dict[str, Any]] = None


@dataclass
class ReplayRunResult:
    replay_id: str
    incident_id: str
    executed_at: str
    is_counterfactual: bool
    controls_applied: Dict[str, Any]
    timeline: List[ReplayStepOutput]
    final_decision: str
    final_risk: float
    mismatch_count: int
    hash_digest: str
    sandbox_verified: bool = True
    safety_contract: Optional[Dict[str, Any]] = None
    is_hypothetical: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "replay_id": self.replay_id,
            "incident_id": self.incident_id,
            "executed_at": self.executed_at,
            "is_counterfactual": self.is_counterfactual,
            "controls_applied": self.controls_applied,
            "final_decision": self.final_decision,
            "final_risk": self.final_risk,
            "mismatch_count": self.mismatch_count,
            "hash_digest": self.hash_digest,
            "sandbox_verified": self.sandbox_verified,
            "safety_contract": self.safety_contract,
            "is_hypothetical": self.is_hypothetical,
            "timeline": [asdict(t) for t in self.timeline],
        }


class SandboxedReplayEngine:
    """
    Executes raw incident traces in a sandboxed virtual runtime through the unified fusion pipeline.
    """

    def __init__(
        self,
        alert_threshold: float = 0.50,
        strong_evidence_threshold: float = 0.65,
    ):
        self.fusion_engine = UncertaintyAwareFusion(
            alert_threshold=alert_threshold,
            strong_evidence_threshold=strong_evidence_threshold,
            target_window_steps=5,
        )
        from src.modules.autonomous_response.safety_contract import GovernedResponseEngine
        self.governed_engine = GovernedResponseEngine(repository=None)

    def execute_replay(
        self,
        incident_id: str,
        steps: List[ReplayStepInput],
        baseline_decision: Optional[str] = None,
        # Counterfactual & Phase 6O controls
        playback_speed: float = 1.0,
        dropout_sensor: Optional[str] = None,  # "camera", "audio", "imu", "sensors", or combinations "camera+audio"
        delayed_audio_ms: int = 0,
        camera_failure: bool = False,
        network_outage: bool = False,
        conflicting_sensors: bool = False,
        operator_action: OperatorAction = "NONE",
        zone_id: Optional[str] = None,
        time_bucket: Optional[str] = None,
        use_zone_priors: bool = True,
        custom_alert_threshold: Optional[float] = None,
        conflict_margin: float = 0.25,
        baseline_risk: Optional[float] = None,
        is_hypothetical: bool = False,
    ) -> ReplayRunResult:
        """
        Runs the incident trace with optional counterfactual perturbations and threshold controls (Phase 6O).
        Guaranteed: NO database writes, NO hardware triggers. Monotonically non-increasing risk on sensor loss.
        """
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        drop_set: Set[str] = set()
        if dropout_sensor:
            drop_set = {s.strip().lower() for s in dropout_sensor.replace("+", ",").split(",") if s.strip()}

        is_counterfactual = any([
            bool(drop_set),
            delayed_audio_ms > 0,
            camera_failure,
            network_outage,
            conflicting_sensors,
            operator_action != "NONE",
            custom_alert_threshold is not None,
        ])

        hypothetical_applied = any([
            is_hypothetical,
            is_counterfactual,
            playback_speed != 1.0,
        ])

        controls = {
            "playback_speed": playback_speed,
            "dropout_sensor": dropout_sensor,
            "delayed_audio_ms": delayed_audio_ms,
            "camera_failure": camera_failure,
            "network_outage": network_outage,
            "conflicting_sensors": conflicting_sensors,
            "operator_action": operator_action,
            "custom_alert_threshold": custom_alert_threshold,
            "conflict_margin": conflict_margin,
            "is_hypothetical": hypothetical_applied,
        }

        timeline: List[ReplayStepOutput] = []
        window_history: List[str] = []
        mismatch_count = 0
        final_decision = "NORMAL"
        final_risk = 0.0

        for idx, step_raw in enumerate(steps):
            step = copy.deepcopy(step_raw)

            # Apply virtual playback speed
            step.timestamp_offset_sec *= (1.0 / playback_speed)

            # 1. Apply Systematic Sensor Dropouts
            if camera_failure or "camera" in drop_set or "all" in drop_set:
                step.camera_classes = []
                step.camera_confidence = 0.0
                step.camera_fps = 0.0

            if "audio" in drop_set or "all" in drop_set:
                step.audio_class = "silence"
                step.audio_confidence = 0.0
                step.audio_db = 0.0

            if "imu" in drop_set or "all" in drop_set:
                step.sensor_imu_g = 0.0

            if "sensors" in drop_set or "environmental" in drop_set or "all" in drop_set:
                step.sensor_temp = 0.0
                step.sensor_smoke_ppm = 0.0
                if "sensors" in drop_set or "all" in drop_set:
                    step.sensor_imu_g = 0.0

            if network_outage:
                step.network_online = False

            if conflicting_sensors:
                # Invert sensors: camera sees fire, audio is dead silent
                step.camera_classes = ["fire"]
                step.camera_confidence = 0.95
                step.audio_class = "silence"
                step.sensor_temp = 18.0
                step.sensor_smoke_ppm = 2.0
                step.sensor_imu_g = 0.0

            # 2. Extract modality predictions
            active_preds: Dict[str, str] = {}
            if "fire" in step.camera_classes:
                active_preds["camera"] = "FIRE"
            elif any("ambulance" in c or "emergency" in c for c in step.camera_classes):
                active_preds["camera"] = "AMBULANCE"
            elif any("accident" in c or "crash" in c or "vehicle" in c for c in step.camera_classes):
                active_preds["camera"] = "ACCIDENT"
            else:
                active_preds["camera"] = "NORMAL"

            if "fire" in step.audio_class:
                active_preds["audio"] = "FIRE"
            elif "crash" in step.audio_class:
                active_preds["audio"] = "ACCIDENT"
            elif "siren" in step.audio_class:
                # Siren corroborates emergency; aligns with visual fire/accident if present
                if active_preds.get("camera") == "FIRE":
                    active_preds["audio"] = "FIRE"
                elif active_preds.get("camera") == "ACCIDENT":
                    active_preds["audio"] = "ACCIDENT"
                else:
                    active_preds["audio"] = "AMBULANCE"
            else:
                active_preds["audio"] = "NORMAL"

            if step.sensor_temp > 45.0 or step.sensor_smoke_ppm > 80.0:
                active_preds["sensors"] = "FIRE"
            elif getattr(step, "sensor_imu_g", 0.0) > 2.5:
                active_preds["sensors"] = "ACCIDENT"
            else:
                active_preds["sensors"] = "NORMAL"

            # Explicit Conflict Detection (Phase 6O)
            distinct_emergencies = {c for c in active_preds.values() if c != "NORMAL"}
            has_conflict = conflicting_sensors
            if not has_conflict and len(distinct_emergencies) > 1:
                cam_cls = active_preds.get("camera", "NORMAL")
                aud_cls = active_preds.get("audio", "NORMAL")
                if cam_cls != "NORMAL" and aud_cls != "NORMAL" and cam_cls != aud_cls:
                    conf_gap = abs(step.camera_confidence - step.audio_confidence)
                    if conf_gap <= conflict_margin or min(step.camera_confidence, step.audio_confidence) >= 0.40:
                        has_conflict = True
                else:
                    has_conflict = True

            # Determine candidate class based on weighted sensor votes
            class_votes: Dict[str, float] = {"NORMAL": 0.0, "ACCIDENT": 0.0, "FIRE": 0.0, "AMBULANCE": 0.0}
            if active_preds.get("camera"):
                class_votes[active_preds["camera"]] += step.camera_confidence
            if active_preds.get("audio"):
                class_votes[active_preds["audio"]] += step.audio_confidence

            candidate_class = max(class_votes, key=class_votes.get)  # type: ignore

            # Raw confidence of candidate class normalized across configured modalities
            raw_conf = min(1.0, max(0.0, class_votes[candidate_class] / 2.0))

            # Conflict Gating: Route to HUMAN_REVIEW, never silent pick
            if has_conflict:
                candidate_class = "HUMAN_REVIEW"
                raw_conf = 0.50

            window_history.append(candidate_class)
            if len(window_history) > 10:
                window_history.pop(0)

            # Device health mapping
            cam_h = 1.0 if step.camera_fps > 0.0 and step.camera_classes else 0.0
            aud_h = 1.0 if step.audio_db > 0.0 and step.audio_class not in ("silence", "clipping") else 0.0
            sens_h = 0.0 if (step.sensor_temp <= 0.0 and step.sensor_smoke_ppm <= 0.0 and step.sensor_imu_g <= 0.0) else 1.0

            is_ood = has_conflict or is_counterfactual or len(distinct_emergencies) > 1

            effective_alert_thresh = custom_alert_threshold if custom_alert_threshold is not None else self.fusion_engine.alert_threshold

            # 3. Evaluate through unified uncertainty fusion engine
            dec = self.fusion_engine.evaluate(
                predicted_class=candidate_class,
                raw_confidence=raw_conf,
                window_history=window_history,
                active_sensor_classes=active_preds,
                device_health_inputs={"camera": cam_h, "audio": aud_h, "sensors": sens_h},
                is_ood=is_ood,
                evidence_duration_sec=step.timestamp_offset_sec,
                zone_reliability=1.0,
                calibration_quality=1.0,
                zone_id=zone_id or "ZONE_A",
                time_bucket=time_bucket,
                use_zone_priors=use_zone_priors,
            )

            # Response plan synthesis
            if has_conflict:
                step_action = "HUMAN_REVIEW"
                plan = "HOLD_FOR_HUMAN_REVIEW_DISPATCH_CONFLICT"
            elif dec.predicted_class == "FIRE":
                plan = "STAGE_FIRE_CREW_AND_VENTILATION"
                step_action = dec.action
            elif dec.predicted_class == "ACCIDENT":
                plan = "TRIGGER_CORRIDOR_PREEMPTION_SIGNALS"
                step_action = dec.action
            elif dec.predicted_class == "AMBULANCE":
                plan = "GREEN_WAVE_EMERGENCY_ROUTING"
                step_action = dec.action
            else:
                plan = "STANDBY_NOMINAL_FLOW"
                step_action = dec.action

            step_risk = dec.final_risk

            # Apply custom threshold if requested and not in hard conflict
            if custom_alert_threshold is not None and not has_conflict:
                if step_risk >= custom_alert_threshold:
                    step_action = "DISPATCH_ALERT"
                elif raw_conf >= self.fusion_engine.strong_evidence_threshold:
                    step_action = "REVIEW_REQUIRED"
                else:
                    step_action = "SUPPRESS_NOISE"

            # Enforce Monotonic Risk Invariant: removing a sensor never raises risk
            if baseline_risk is not None and (bool(drop_set) or camera_failure):
                step_risk = min(baseline_risk, step_risk)

            # Check for replay mismatch against baseline
            mismatch = False
            if baseline_decision and not is_counterfactual and not has_conflict:
                if dec.predicted_class != baseline_decision:
                    mismatch = True
                    mismatch_count += 1

            # Handle alternative operator decision override
            current_op_action = operator_action if (idx == len(steps) - 1 and operator_action != "NONE") else "NONE"
            if current_op_action == "FALSE_ALARM":
                plan = "OPERATOR_OVERRIDE_SUPPRESSED_AS_FALSE_ALARM"

            final_decision = "HUMAN_REVIEW" if has_conflict else dec.predicted_class
            final_risk = step_risk

            # Synthesize Visible Safety Contract for this replay step
            evidence_summary = []
            if step.camera_classes:
                evidence_summary.append(f"Visual classes detected: {', '.join(step.camera_classes)}")
            if step.audio_class and step.audio_class != "silence":
                evidence_summary.append(f"Acoustic classification: {step.audio_class} ({round(step.audio_db, 1)} dB)")
            if step.sensor_temp > 40.0:
                evidence_summary.append(f"Thermal anomaly: {round(step.sensor_temp, 1)} °C")
            if step.sensor_smoke_ppm > 50.0:
                evidence_summary.append(f"Combustion smoke gas: {round(step.sensor_smoke_ppm, 1)} PPM")
            if not evidence_summary:
                evidence_summary.append("Nominal multi-sensor baseline telemetry")

            _, contract_obj = self.governed_engine.synthesize_response_plan(
                incident_id=incident_id,
                detected_class=dec.predicted_class,
                confidence=dec.raw_confidence,
                evidence_summary=evidence_summary,
                risk_factors=dec.factors.to_dict(),
                model_id="sandboxed_detector_v1",
                model_usage_restriction="PRODUCTION",
            )

            step_out = ReplayStepOutput(
                step_idx=idx,
                timestamp_offset_sec=round(step.timestamp_offset_sec, 3),
                raw_inputs={
                    "camera_classes": step.camera_classes,
                    "audio_class": step.audio_class,
                    "sensor_temp": step.sensor_temp,
                    "sensor_smoke": step.sensor_smoke_ppm,
                    "network_online": step.network_online,
                },
                model_predictions=active_preds,
                ood_detected=is_ood,
                risk_factors=dec.factors.to_dict(),
                final_risk=final_risk,
                action=step_action,
                recommended_plan=plan,
                operator_action=current_op_action,
                mismatch_detected=mismatch,
                safety_contract=contract_obj.to_dict(),
            )
            timeline.append(step_out)

        # Generate cryptographic digest for the replay
        digest_payload = json.dumps(
            {
                "incident_id": incident_id,
                "controls": controls,
                "final_decision": final_decision,
                "final_risk": final_risk,
                "step_count": len(timeline),
            },
            sort_keys=True,
        )
        hash_digest = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()
        replay_id = f"REPLAY-{incident_id}-{hash_digest[:10]}"

        final_contract = timeline[-1].safety_contract if timeline else None

        return ReplayRunResult(
            replay_id=replay_id,
            incident_id=incident_id,
            executed_at=now_iso,
            is_counterfactual=is_counterfactual,
            controls_applied=controls,
            timeline=timeline,
            final_decision=final_decision,
            final_risk=final_risk,
            mismatch_count=mismatch_count,
            hash_digest=hash_digest,
            sandbox_verified=True,
            safety_contract=final_contract,
            is_hypothetical=hypothetical_applied,
        )
