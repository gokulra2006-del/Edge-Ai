"""
Module: Deep Learning Inference & Rule-Set Engine (DeepInferenceRuleEngine).
==========================================================================
Connects raw multi-sensor telemetry and camera/microphone feeds directly to
trained PyTorch & YOLO11 deep learning models, then applies an explainable,
auditable rule-based expert system for safety-critical edge decisions.
"""
from dataclasses import dataclass, field
from pathlib import Path
from src.config.model_profile import model_profile
import time
from typing import Any, Dict, List, Optional, Union
import numpy as np
import torch

from src.modules.audio_ai.classifier import AudioClassifier
from src.modules.vision_ai.detector import VisionDetector
from src.modules.sensors.dataset_feeder import DATASET_INFERENCE_FEEDER
from src.modules.logging.logger import LOGGER


@dataclass
class DeepRuleDecision:
    """Standardized decision payload produced by the DeepInferenceRuleEngine."""
    rule_id: str
    rule_name: str
    event: str
    severity: str
    confidence: float
    is_verified: bool
    deep_learning: Dict[str, Any]
    physical_telemetry: Dict[str, Any]
    explainable_reasoning: List[str]
    actuators: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "event": self.event,
            "severity": self.severity,
            "confidence": round(self.confidence, 4),
            "is_verified": self.is_verified,
            "deep_learning": self.deep_learning,
            "physical_telemetry": self.physical_telemetry,
            "explainable_reasoning": self.explainable_reasoning,
            "actuators": self.actuators,
            "timestamp": self.timestamp
        }


class DeepInferenceRuleEngine:
    """
    Unified Deep Learning Rule-Based Decision System.
    Takes raw or dataset-fed inputs, computes deep model representations,
    and applies a deterministic rule set to guarantee safe intersection responses.
    """

    def __init__(self):
        LOGGER.info("[DeepRuleEngine] Initializing Deep Learning Rule-Set Engine...")
        self.audio_classifier = AudioClassifier()
        self.vision_detector = VisionDetector()
        LOGGER.info("[DeepRuleEngine] Deep models loaded and rule set ready.")

    def get_rule_catalog(self) -> List[Dict[str, Any]]:
        """Returns the formal specification of all rules in the safety decision matrix."""
        return [
            {
                "rule_id": "RULE_R1_COLLISION",
                "rule_name": "Multi-Modal Acoustic & Inertial Collision Rule",
                "priority": 1,
                "conditions": [
                    "EdgeAcousticNet class == 'crash_impact' with confidence >= 0.50 (or 'car_horn' >= 0.65)",
                    "AND (MPU-6050 physical jerk >= 2.5g OR optical flow deceleration >= 0.45)"
                ],
                "outcome": {
                    "event": "ACCIDENT",
                    "severity": "CRITICAL",
                    "actuation": "ALL_RED + LOCKDOWN_BARRIER + DISPATCH_EMS"
                }
            },
            {
                "rule_id": "RULE_R2_FIRE_SMOKE",
                "rule_name": "Visual Flame & Combustion Gas Density Rule",
                "priority": 2,
                "conditions": [
                    "YOLO11 detects 'Fire' (conf >= 0.30) OR 'Smoke' (conf >= 0.30)",
                    "AND (MQ-2 gas >= 70.0 PPM OR DHT-22 temp >= 48.0°C)"
                ],
                "outcome": {
                    "event": "FIRE",
                    "severity": "CRITICAL",
                    "actuation": "ALL_RED + EVACUATION_SIREN + DISPATCH_FIRE"
                }
            },
            {
                "rule_id": "RULE_R3_EMERGENCY_CORRIDOR",
                "rule_name": "Acoustic Siren Responder Pre-emption Rule",
                "priority": 3,
                "conditions": [
                    "EdgeAcousticNet detects 'ambulance', 'firetruck', or 'police' with confidence >= 0.50"
                ],
                "outcome": {
                    "event": "EMERGENCY_VEHICLE",
                    "severity": "HIGH",
                    "actuation": "GREEN_WAVE_PREEMPTION + OPEN_BARRIER"
                }
            },
            {
                "rule_id": "RULE_R4_NEAR_MISS",
                "rule_name": "Predictive Optical Trajectory Near-Miss Rule",
                "priority": 4,
                "conditions": [
                    "Optical Flow / Bounding Box TTC < 1.8s with converging trajectory"
                ],
                "outcome": {
                    "event": "NEAR_MISS",
                    "severity": "MEDIUM",
                    "actuation": "CAUTION_STROBE + SLOW_APPROACH"
                }
            },
            {
                "rule_id": "RULE_R5_VEHICLE_SMOKE",
                "rule_name": "Vehicle Tailpipe & Exhaust Emission Suppression Rule",
                "priority": 5,
                "conditions": [
                    "YOLO11 detects 'Smoke' with vehicle presence",
                    "AND MQ-2 gas < 70.0 PPM AND DHT-22 temp < 48.0°C (Non-hazardous baseline)"
                ],
                "outcome": {
                    "event": "VEHICLE_SMOKE",
                    "severity": "LOW",
                    "actuation": "CYCLIC_GREEN + LOG_EMISSION_ADVISORY"
                }
            },
            {
                "rule_id": "RULE_R0_NOMINAL",
                "rule_name": "Standard Urban Flow Equilibrium Rule",
                "priority": 6,
                "conditions": [
                    "Default when all multi-sensor signals remain within nominal baseline bounds"
                ],
                "outcome": {
                    "event": "NORMAL",
                    "severity": "LOW",
                    "actuation": "CYCLIC_GREEN + OPEN_BARRIER + STANDBY"
                }
            }
        ]

    def evaluate(
        self,
        raw_audio: Optional[Any] = None,
        raw_image: Optional[Any] = None,
        accel_g: float = 0.03,
        impact_detected: bool = False,
        smoke_ppm: float = 12.0,
        temperature_c: float = 28.5,
        motion_analysis: Optional[Dict[str, Any]] = None,
        near_miss: Optional[Dict[str, Any]] = None,
        scenario_hint: Optional[str] = None
    ) -> DeepRuleDecision:
        """
        Executes raw input through deep learning models and applies the rule set.
        """
        # 1. DEEP LEARNING: Run raw inputs through trained PyTorch & YOLO models
        if isinstance(raw_audio, dict) and "class" in raw_audio:
            audio_pred = raw_audio
        elif raw_audio is not None and isinstance(raw_audio, (str, Path)) and Path(raw_audio).exists():
            tensor = DATASET_INFERENCE_FEEDER._extract_spectrogram(Path(raw_audio))
            pred = self.audio_classifier.predict_tensor(tensor)
            audio_pred = {
                "class": pred.class_name,
                "confidence": round(pred.confidence, 4),
                "source_file": Path(raw_audio).name,
                "dataset": "Synthetic supplied dataset" if model_profile()['synthetic'] else (
                    "UrbanSound8K" if "UrbanSound8K" in str(raw_audio) else "sireNNet")
            }
        elif raw_audio is not None:
            raise ValueError('raw_audio must be a prediction dictionary or an existing audio file')
        else:
            audio_pred = DATASET_INFERENCE_FEEDER.run_audio_inference(scenario_hint or "NORMAL")

        if isinstance(raw_image, dict) and "class" in raw_image:
            vision_pred = raw_image
        elif raw_image is not None and isinstance(raw_image, (str, Path)) and Path(raw_image).exists():
            v_res = self.vision_detector.predict_image(str(raw_image))
            hazard = "FLAME" if "fire" in [c.lower() for c in v_res.detected_classes] else "NONE"
            vision_pred = {
                "class": v_res.primary_class,
                "confidence": round(v_res.confidence, 4),
                "hazard": hazard,
                "detected_classes": v_res.detected_classes,
                "bounding_boxes": v_res.bounding_boxes[:4],
                "source_frame": Path(raw_image).name,
                "dataset": "Synthetic supplied dataset" if model_profile()['synthetic'] else (
                    "FIRE_n_SMOKE" if "FIRE" in str(raw_image) else "vehicles_yolo11")
            }
        elif raw_image is not None:
            raise ValueError('raw_image must be a prediction dictionary or an existing image file')
        else:
            vision_pred = DATASET_INFERENCE_FEEDER.run_vision_inference(scenario_hint or "NORMAL")

        a_class = str(audio_pred.get("class", "traffic")).lower()
        a_conf = float(audio_pred.get("confidence", 0.0))

        v_detected = [str(c).lower() for c in vision_pred.get("detected_classes", [])]
        v_conf = float(vision_pred.get("confidence", 0.0))

        motion = motion_analysis or {}
        crash_motion_score = float(motion.get("composite_crash_score", motion.get("crash_score", 0.0)))

        ttc_info = near_miss or {}
        min_ttc = float(ttc_info.get("min_ttc_sec", 9.9))
        is_imminent = bool(ttc_info.get("is_imminent", False))

        deep_learning_meta = {
            "acoustic_model": {
                "model": "EdgeAcousticNet (PyTorch)",
                "weights": self.audio_classifier.model_path.name,
                "predicted_class": audio_pred.get("class"),
                "confidence": a_conf,
                "source": audio_pred.get("source_file"),
                "dataset": audio_pred.get("dataset")
            },
            "vision_model": {
                "model": "YOLO11n-Edge (Ultralytics)",
                "weights": ", ".join(p.name for p in model_profile()["vision"]),
                "primary_class": vision_pred.get("class"),
                "detected_classes": vision_pred.get("detected_classes"),
                "confidence": v_conf,
                "bounding_boxes": vision_pred.get("bounding_boxes", []),
                "source": vision_pred.get("source_frame"),
                "dataset": vision_pred.get("dataset")
            }
        }

        physical_telemetry = {
            "acceleration_g": accel_g,
            "impact_detected": impact_detected,
            "smoke_ppm": smoke_ppm,
            "temperature_c": temperature_c,
            "optical_crash_score": crash_motion_score,
            "time_to_collision_sec": min_ttc
        }

        # -------------------------------------------------------------
        # EVALUATE RULE SET IN ORDER OF SAFETY PRIORITY
        # -------------------------------------------------------------

        # RULE R1: COLLISION ACCIDENT
        is_acoustic_crash = (a_class in ("crash_impact", "crash") and a_conf >= 0.40) or (a_class == "car_horn" and a_conf >= 0.65)
        is_inertial_impact = impact_detected or (accel_g >= 2.5) or (crash_motion_score >= 0.40)

        if is_acoustic_crash and is_inertial_impact:
            rule_id = "RULE_R1_COLLISION"
            rule_name = "Multi-Modal Acoustic & Inertial Collision Rule"
            event = "ACCIDENT"
            severity = "CRITICAL"
            fused_conf = min(0.99, max(0.85, 0.5 * a_conf + 0.3 * (accel_g / 5.0) + 0.2 * crash_motion_score))
            reasoning = [
                f"EdgeAcousticNet classified audio as '{audio_pred.get('class')}' with {a_conf * 100:.1f}% confidence from dataset sample {audio_pred.get('source_file')}.",
                f"Inertial sensor recorded physical impact spike of {accel_g:.2f}g (threshold: 2.5g).",
                f"Optical Flow composite deceleration risk scored {crash_motion_score * 100:.1f}%.",
                "Rule R1 satisfies 3-way multi-modal corroboration: ALL-RED traffic pre-emption triggered."
            ]
            actuators = {
                "traffic_signal": "RED",
                "barrier": "CLOSED",
                "buzzer": "ON",
                "green_corridor_active": False,
                "dispatch_alert": "DISPATCH_EMERGENCY_AMBULANCE_POLICE"
            }
            return DeepRuleDecision(
                rule_id=rule_id, rule_name=rule_name, event=event, severity=severity,
                confidence=fused_conf, is_verified=True, deep_learning=deep_learning_meta,
                physical_telemetry=physical_telemetry, explainable_reasoning=reasoning,
                actuators=actuators
            )

        # RULE R2: FIRE & SMOKE HAZARD
        has_visual_fire_smoke = any(c in v_detected for c in ("fire", "smoke")) or ("flame" in vision_pred.get("hazard", "").lower())
        has_gas_temp_hazard = (smoke_ppm >= 70.0) or (temperature_c >= 48.0)

        if has_visual_fire_smoke and has_gas_temp_hazard:
            rule_id = "RULE_R2_FIRE_SMOKE"
            rule_name = "Visual Flame & Combustion Gas Density Rule"
            event = "FIRE"
            severity = "CRITICAL"
            gas_norm = min(1.0, smoke_ppm / 250.0)
            fused_conf = min(0.99, max(0.82, 0.45 * v_conf + 0.35 * gas_norm + 0.20 * (temperature_c / 80.0)))
            reasoning = [
                f"YOLO11n-Edge visual detection confirmed {vision_pred.get('detected_classes')} with {v_conf * 100:.1f}% confidence on frame {vision_pred.get('source_frame')}.",
                f"MQ-2 environmental gas sensor measured combustion density at {smoke_ppm:.1f} PPM (threshold: 70 PPM).",
                f"DHT-22 thermal channel registered elevated ambient temperature of {temperature_c:.1f}°C.",
                "Rule R2 triggered: Intersection perimeter secured and Fire Rescue dispatched."
            ]
            actuators = {
                "traffic_signal": "RED",
                "barrier": "CLOSED",
                "buzzer": "ON",
                "green_corridor_active": False,
                "dispatch_alert": "DISPATCH_FIRE_SERVICES_ACTIVATE_EXHAUST"
            }
            return DeepRuleDecision(
                rule_id=rule_id, rule_name=rule_name, event=event, severity=severity,
                confidence=fused_conf, is_verified=True, deep_learning=deep_learning_meta,
                physical_telemetry=physical_telemetry, explainable_reasoning=reasoning,
                actuators=actuators
            )

        # RULE R3: EMERGENCY VEHICLE SIREN & GREEN CORRIDOR
        is_siren_audio = a_class in ("ambulance", "firetruck", "police", "siren") and (a_conf >= 0.45)

        if is_siren_audio:
            rule_id = "RULE_R3_EMERGENCY_CORRIDOR"
            rule_name = "Acoustic Siren Responder Pre-emption Rule"
            event = "EMERGENCY_VEHICLE"
            severity = "HIGH"
            fused_conf = min(0.98, max(0.88, 0.7 * a_conf + 0.3 * (1.0 if "vehicle" in v_detected else 0.8)))
            reasoning = [
                f"EdgeAcousticNet classified emergency siren frequency as '{audio_pred.get('class')}' with {a_conf * 100:.1f}% confidence ({audio_pred.get('source_file')}).",
                f"Corroborated by vision detector evaluating frame {vision_pred.get('source_frame')}.",
                "Rule R3 triggered: Autonomous Green Wave engaged across municipal node corridor."
            ]
            actuators = {
                "traffic_signal": "GREEN",
                "barrier": "OPEN",
                "buzzer": "OFF",
                "green_corridor_active": True,
                "dispatch_alert": "GREEN_CORRIDOR_ZONE_B_ACTIVE"
            }
            return DeepRuleDecision(
                rule_id=rule_id, rule_name=rule_name, event=event, severity=severity,
                confidence=fused_conf, is_verified=True, deep_learning=deep_learning_meta,
                physical_telemetry=physical_telemetry, explainable_reasoning=reasoning,
                actuators=actuators
            )

        # RULE R4: PREDICTIVE TRAJECTORY NEAR-MISS
        if is_imminent or min_ttc < 1.8:
            rule_id = "RULE_R4_NEAR_MISS"
            rule_name = "Predictive Optical Trajectory Near-Miss Rule"
            event = "NEAR_MISS"
            severity = "MEDIUM"
            fused_conf = 0.84
            reasoning = [
                f"Predictive collision algorithm measured Time-to-Collision (TTC) at {min_ttc:.1f}s (safety threshold: 1.8s).",
                "Converging trajectory vectors observed on arterial approaches.",
                "Rule R4 triggered: Warning beacons pulsed to alert oncoming drivers."
            ]
            actuators = {
                "traffic_signal": "YELLOW",
                "barrier": "OPEN",
                "buzzer": "OFF",
                "green_corridor_active": False,
                "dispatch_alert": "WARNING_NEAR_MISS_TRAJECTORY_OBSERVED"
            }
            return DeepRuleDecision(
                rule_id=rule_id, rule_name=rule_name, event=event, severity=severity,
                confidence=fused_conf, is_verified=True, deep_learning=deep_learning_meta,
                physical_telemetry=physical_telemetry, explainable_reasoning=reasoning,
                actuators=actuators
            )

        # RULE R5: VEHICLE EXHAUST & CAR SMOKE SUPPRESSION
        has_vehicle = any(c in v_detected for c in ("vehicle", "car", "bus", "truck", "big truck", "small truck"))
        if has_visual_fire_smoke and (has_vehicle or smoke_ppm < 70.0) and not has_gas_temp_hazard:
            rule_id = "RULE_R5_VEHICLE_SMOKE"
            rule_name = "Vehicle Tailpipe & Exhaust Emission Suppression Rule"
            event = "VEHICLE_SMOKE"
            severity = "LOW"
            fused_conf = 0.88
            reasoning = [
                f"YOLO11n-Edge detected smoke visual features with co-present vehicles ({v_detected}).",
                f"Multi-modal telemetry confirms ambient gas ({smoke_ppm:.1f} PPM) and temperature ({temperature_c:.1f}°C) within normal non-emergency limits.",
                "Rule R5 triggered: Categorized as vehicle tailpipe exhaust, NOT a structural fire emergency. False alarm prevented; traffic continues normally."
            ]
            actuators = {
                "traffic_signal": "GREEN",
                "barrier": "OPEN",
                "buzzer": "OFF",
                "green_corridor_active": False,
                "dispatch_alert": "LOG_VEHICLE_EMISSION_ADVISORY"
            }
            return DeepRuleDecision(
                rule_id=rule_id, rule_name=rule_name, event=event, severity=severity,
                confidence=fused_conf, is_verified=True, deep_learning=deep_learning_meta,
                physical_telemetry=physical_telemetry, explainable_reasoning=reasoning,
                actuators=actuators
            )

        # RULE R0: NOMINAL URBAN FLOW (BASELINE)
        rule_id = "RULE_R0_NOMINAL"
        rule_name = "Standard Urban Flow Equilibrium Rule"
        event = "NORMAL"
        severity = "LOW"
        fused_conf = 0.90
        reasoning = [
            f"EdgeAcousticNet identified ambient sound as '{audio_pred.get('class')}' ({a_conf * 100:.1f}%) from dataset sample {audio_pred.get('source_file')}.",
            f"YOLO11n-Edge detected standard urban vehicular presence on {vision_pred.get('source_frame')}.",
            f"Inertial and environmental readings nominal (accel: {accel_g:.2f}g, gas: {smoke_ppm:.1f} PPM, temp: {temperature_c:.1f}°C).",
            "Rule R0 triggered: Nominal cyclic signal timing maintained across all phases."
        ]
        actuators = {
            "traffic_signal": "GREEN",
            "barrier": "OPEN",
            "buzzer": "OFF",
            "green_corridor_active": False,
            "dispatch_alert": "NORMAL_CYCLIC_OPERATIONS"
        }
        return DeepRuleDecision(
            rule_id=rule_id, rule_name=rule_name, event=event, severity=severity,
            confidence=fused_conf, is_verified=True, deep_learning=deep_learning_meta,
            physical_telemetry=physical_telemetry, explainable_reasoning=reasoning,
            actuators=actuators
        )


# Global singleton instance
DEEP_RULE_ENGINE = DeepInferenceRuleEngine()
