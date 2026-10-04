"""
Module 9: Live Edge Telemetry Streamer & Scenario Controller.
============================================================
Runs continuous sensor cycles on the Raspberry Pi / laptop,
periodically updating telemetry, running emergency evaluations,
coordinating Blackbox DVR recording, Optical Flow motion tracking,
Temporal Sensor Fusion, Alert Dispatch, and Green Wave routing.
"""
import math
import random
import threading
import time
from typing import Any, Dict
from src.config.model_profile import model_profile
import numpy as np

from src.modules.autonomous_response.alert_manager import ALERT_MANAGER
from src.modules.autonomous_response.green_wave_coordinator import GREEN_WAVE
from src.modules.autonomous_response.multi_intersection import MUNICIPAL_GRID
from src.modules.dashboard.firebase_sync import FIREBASE_SYNC
from src.modules.database.db_manager import DatabaseManager
from src.modules.logging.logger import LOGGER
from src.modules.recording.blackbox_dvr import DVR
from src.modules.sensors.dataset_feeder import DATASET_INFERENCE_FEEDER
from src.modules.decision_engine.deep_rule_engine import DEEP_RULE_ENGINE
from src.modules.sensor_fusion.temporal_verifier import TEMPORAL_VERIFIER
from src.modules.vision_ai.motion_tracker import MOTION_TRACKER
from src.modules.vision_ai.near_miss_analyzer import NEAR_MISS_ANALYZER


class LiveEdgeStreamer:
    """
    Manages continuous live data streaming from Raspberry Pi edge node to
    Firebase and local web clients, integrating advanced edge intelligence modules.
    """

    def __init__(self, interval_sec: float = 1.0):
        self.interval_sec = interval_sec
        self.is_running = False
        self._thread = None
        self.db = DatabaseManager()

        # Active scenario state
        self.active_scenario = "NORMAL"
        self.scenario_timer = 0
        self.cycle_count = 0

        # Feed Blackbox DVR with simulated frames
        self._dummy_frame = np.ones((360, 640, 3), dtype=np.uint8) * 30

    def start(self):
        """Start the background streaming daemon."""
        if self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="EdgeTelemetryStreamer")
        self._thread.start()
        LOGGER.info("LiveEdgeStreamer background service started.")

    def stop(self):
        """Stop streaming."""
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        LOGGER.info("LiveEdgeStreamer stopped.")

    def trigger_scenario(self, scenario: str) -> Dict[str, Any]:
        """
        Manually trigger an emergency scenario from the Web Dashboard.
        Supported scenarios: 'ACCIDENT', 'FIRE', 'AMBULANCE', 'NORMAL'.
        """
        scenario = scenario.upper().strip()
        if scenario not in ("ACCIDENT", "FIRE", "AMBULANCE", "NORMAL"):
            scenario = "NORMAL"

        self.active_scenario = scenario
        self.scenario_timer = 15  # Keep scenario active for 15 seconds before resuming normal baseline

        LOGGER.warning(f"[OPERATOR TRIGGER] Web Dashboard initiated scenario: {self.active_scenario}")
        return self._generate_and_sync_cycle()

    def _generate_and_sync_cycle(self) -> Dict[str, Any]:
        """Generate sensor telemetry for current state and sync to Firebase & DVR."""
        self.cycle_count += 1
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")

        temp_noise = random.uniform(-0.3, 0.3)
        smoke_noise = random.uniform(-1.0, 1.0)

        # Continually feed Blackbox DVR circular buffer in RAM
        DVR.add_frame(self._dummy_frame)

        # -------------------------------------------------------------
        # SCENARIO 1: ACCIDENT (Collision + Deceleration + Audio Crash)
        # -------------------------------------------------------------
        if self.active_scenario == "ACCIDENT":
            dummy_boxes = [[120, 100, 260, 220], [240, 110, 380, 230]]
            motion_res = MOTION_TRACKER.update(self._dummy_frame, dummy_boxes, imu_impact_score=1.0)
            ttc_res = NEAR_MISS_ANALYZER.evaluate_trajectories(dummy_boxes)

            accel_val = round(random.uniform(4.5, 6.2), 2)
            temp_val = round(32.5 + temp_noise, 1)
            smoke_val = round(35.0 + smoke_noise, 1)

            decision = DEEP_RULE_ENGINE.evaluate(
                raw_audio={"class": "crash_impact", "confidence": round(random.uniform(0.85, 0.96), 4), "source_file": "174290-6-3-0.wav", "dataset": "UrbanSound8K"} if not model_profile()['synthetic'] else None,
                accel_g=accel_val,
                impact_detected=True,
                smoke_ppm=smoke_val,
                temperature_c=temp_val,
                motion_analysis=motion_res,
                near_miss=ttc_res,
                scenario_hint="ACCIDENT"
            )

            telemetry = {
                "temperature": temp_val,
                "smoke_level": smoke_val,
                "impact_detected": True,
                "acceleration_g": accel_val,
                "audio_prediction": {
                    "class": decision.deep_learning["acoustic_model"]["predicted_class"],
                    "confidence": decision.deep_learning["acoustic_model"]["confidence"],
                    "source_file": decision.deep_learning["acoustic_model"]["source"],
                    "dataset": decision.deep_learning["acoustic_model"]["dataset"]
                },
                "vision_prediction": {
                    "class": decision.deep_learning["vision_model"]["primary_class"],
                    "confidence": decision.deep_learning["vision_model"]["confidence"],
                    "hazard": "COLLISION",
                    "detected_classes": decision.deep_learning["vision_model"]["detected_classes"],
                    "bounding_boxes": decision.deep_learning["vision_model"]["bounding_boxes"],
                    "source_frame": decision.deep_learning["vision_model"]["source"],
                    "dataset": decision.deep_learning["vision_model"]["dataset"]
                },
                "cpu_temp": round(44.2 + temp_noise, 1),
                "fps": 14.8,
                "timestamp": now_iso,
                "motion_analysis": motion_res,
                "near_miss_analysis": ttc_res,
                "rule_id": decision.rule_id,
                "rule_name": decision.rule_name,
                "deep_learning": decision.deep_learning
            }

            temporal_res = TEMPORAL_VERIFIER.ingest_cycle(
                audio_class=telemetry["audio_prediction"]["class"],
                audio_conf=telemetry["audio_prediction"]["confidence"],
                vision_class=telemetry["vision_prediction"]["class"],
                vision_conf=telemetry["vision_prediction"]["confidence"],
                impact_detected=True,
                accel_g=accel_val,
                smoke_ppm=smoke_val,
                temp_c=temp_val,
                crash_motion_score=motion_res["composite_crash_score"]
            )

            incident_id = f"INC-ACC-{self.cycle_count}"
            video_file = DVR.trigger_incident_capture(incident_id, "ACCIDENT", post_event_seconds=5)
            MUNICIPAL_GRID.set_emergency_preemption(affected_node="NODE_B", mode="ALL_RED")

            actuators = decision.actuators

            active_event = {
                "id": incident_id,
                "event": decision.event,
                "rule_id": decision.rule_id,
                "rule_name": decision.rule_name,
                "confidence": decision.confidence,
                "severity": decision.severity,
                "zone": "ZONE_B_INTERSECTION",
                "verified": decision.is_verified,
                "sensor_contributions": temporal_res.get("sensor_contributions", {}),
                "explainable_verdict": " • ".join(decision.explainable_reasoning),
                "evidence_chain": decision.explainable_reasoning,
                "video_url": f"/api/recordings/{video_file}",
                "description": "Multi-sensor verified road accident evaluated by Deep Learning Rule Engine (Rule R1).",
                "timestamp": now_iso
            }

            ALERT_MANAGER.post_incident(
                incident_id=incident_id,
                event_type="ACCIDENT",
                severity="CRITICAL",
                confidence=decision.confidence,
                zone="ZONE_B_INTERSECTION",
                evidence=decision.explainable_reasoning,
                actions=["RESTRICT_AFFECTED_LANE_AND_SLOW", "DISPATCH_AMBULANCE_AND_POLICE"],
                video_url=f"/api/recordings/{video_file}"
            )

        # -------------------------------------------------------------
        # SCENARIO 2: FIRE HAZARD (High Smoke + Flame Visual + Heat)
        # -------------------------------------------------------------
        elif self.active_scenario == "FIRE":
            motion_res = MOTION_TRACKER.update(self._dummy_frame, [], imu_impact_score=0.0)

            accel_val = 0.04
            temp_val = round(72.0 + random.uniform(-1.5, 2.5), 1)
            smoke_val = round(265.0 + random.uniform(-5.0, 10.0), 1)

            decision = DEEP_RULE_ENGINE.evaluate(
                raw_image={"class": "Fire", "confidence": 0.88, "hazard": "FLAME", "detected_classes": ["Fire", "Smoke"], "bounding_boxes": [{"class": "Fire", "confidence": 0.88, "box": [130, 170, 320, 250]}], "source_frame": "image_895_jpg.rf.3195085b5b3101a1f5c7bb541c2f7853.jpg", "dataset": "FIRE_n_SMOKE"} if not model_profile()['synthetic'] else None,
                accel_g=accel_val,
                impact_detected=False,
                smoke_ppm=smoke_val,
                temperature_c=temp_val,
                motion_analysis=motion_res,
                scenario_hint="FIRE"
            )

            telemetry = {
                "temperature": temp_val,
                "smoke_level": smoke_val,
                "impact_detected": False,
                "acceleration_g": accel_val,
                "audio_prediction": {
                    "class": decision.deep_learning["acoustic_model"]["predicted_class"],
                    "confidence": decision.deep_learning["acoustic_model"]["confidence"],
                    "source_file": decision.deep_learning["acoustic_model"]["source"],
                    "dataset": decision.deep_learning["acoustic_model"]["dataset"]
                },
                "vision_prediction": {
                    "class": decision.deep_learning["vision_model"]["primary_class"],
                    "confidence": decision.deep_learning["vision_model"]["confidence"],
                    "hazard": "FLAME",
                    "detected_classes": decision.deep_learning["vision_model"]["detected_classes"],
                    "bounding_boxes": decision.deep_learning["vision_model"]["bounding_boxes"],
                    "source_frame": decision.deep_learning["vision_model"]["source"],
                    "dataset": decision.deep_learning["vision_model"]["dataset"]
                },
                "cpu_temp": 48.6,
                "fps": 14.5,
                "timestamp": now_iso,
                "motion_analysis": motion_res,
                "rule_id": decision.rule_id,
                "rule_name": decision.rule_name,
                "deep_learning": decision.deep_learning
            }

            temporal_res = TEMPORAL_VERIFIER.ingest_cycle(
                audio_class=telemetry["audio_prediction"]["class"],
                audio_conf=telemetry["audio_prediction"]["confidence"],
                vision_class=telemetry["vision_prediction"]["class"],
                vision_conf=telemetry["vision_prediction"]["confidence"],
                impact_detected=False,
                accel_g=accel_val,
                smoke_ppm=smoke_val,
                temp_c=temp_val
            )

            incident_id = f"INC-FIRE-{self.cycle_count}"
            video_file = DVR.trigger_incident_capture(incident_id, "FIRE", post_event_seconds=5)

            actuators = decision.actuators

            active_event = {
                "id": incident_id,
                "event": decision.event,
                "rule_id": decision.rule_id,
                "rule_name": decision.rule_name,
                "confidence": decision.confidence,
                "severity": decision.severity,
                "zone": "ZONE_B_INTERSECTION",
                "verified": decision.is_verified,
                "sensor_contributions": temporal_res.get("sensor_contributions", {}),
                "explainable_verdict": " • ".join(decision.explainable_reasoning),
                "evidence_chain": decision.explainable_reasoning,
                "video_url": f"/api/recordings/{video_file}",
                "description": "Severe fire and smoke hazard evaluated by Deep Learning Rule Engine (Rule R2).",
                "timestamp": now_iso
            }

            ALERT_MANAGER.post_incident(
                incident_id=incident_id,
                event_type="FIRE",
                severity="CRITICAL",
                confidence=decision.confidence,
                zone="ZONE_B_INTERSECTION",
                evidence=decision.explainable_reasoning,
                actions=["HALT_APPROACHING_TRAFFIC_ALL_RED", "DISPATCH_FIRE_RESCUE"],
                video_url=f"/api/recordings/{video_file}"
            )

        # -------------------------------------------------------------
        # SCENARIO 3: EMERGENCY VEHICLE (Siren Corridor + Green Wave)
        # -------------------------------------------------------------
        elif self.active_scenario == "AMBULANCE":
            motion_res = MOTION_TRACKER.update(self._dummy_frame, [[100, 150, 220, 280]], imu_impact_score=0.0)

            accel_val = 0.02
            temp_val = round(28.2 + temp_noise, 1)
            smoke_val = round(14.0 + smoke_noise, 1)

            decision = DEEP_RULE_ENGINE.evaluate(
                raw_audio={"class": "ambulance", "confidence": 0.94, "source_file": "sound_43.wav", "dataset": "sireNNet"} if not model_profile()['synthetic'] else None,
                accel_g=accel_val,
                impact_detected=False,
                smoke_ppm=smoke_val,
                temperature_c=temp_val,
                motion_analysis=motion_res,
                scenario_hint="AMBULANCE"
            )

            telemetry = {
                "temperature": temp_val,
                "smoke_level": smoke_val,
                "impact_detected": False,
                "acceleration_g": accel_val,
                "audio_prediction": {
                    "class": decision.deep_learning["acoustic_model"]["predicted_class"],
                    "confidence": decision.deep_learning["acoustic_model"]["confidence"],
                    "source_file": decision.deep_learning["acoustic_model"]["source"],
                    "dataset": decision.deep_learning["acoustic_model"]["dataset"]
                },
                "vision_prediction": {
                    "class": decision.deep_learning["vision_model"]["primary_class"],
                    "confidence": decision.deep_learning["vision_model"]["confidence"],
                    "hazard": "NONE",
                    "detected_classes": decision.deep_learning["vision_model"]["detected_classes"],
                    "bounding_boxes": decision.deep_learning["vision_model"]["bounding_boxes"],
                    "source_frame": decision.deep_learning["vision_model"]["source"],
                    "dataset": decision.deep_learning["vision_model"]["dataset"]
                },
                "cpu_temp": 42.1,
                "fps": 15.1,
                "timestamp": now_iso,
                "motion_analysis": motion_res,
                "rule_id": decision.rule_id,
                "rule_name": decision.rule_name,
                "deep_learning": decision.deep_learning
            }

            temporal_res = TEMPORAL_VERIFIER.ingest_cycle(
                audio_class=telemetry["audio_prediction"]["class"],
                audio_conf=telemetry["audio_prediction"]["confidence"],
                vision_class=telemetry["vision_prediction"]["class"],
                vision_conf=telemetry["vision_prediction"]["confidence"],
                impact_detected=False,
                accel_g=0.02,
                smoke_ppm=telemetry["smoke_level"],
                temp_c=telemetry["temperature"]
            )

            green_wave_plan = GREEN_WAVE.initiate_green_wave(origin_node="NODE_B", target_destination="NODE_D")
            actuators = decision.actuators
            actuators["green_wave_route"] = green_wave_plan

            active_event = {
                "id": f"INC-AMB-{self.cycle_count}",
                "event": decision.event,
                "rule_id": decision.rule_id,
                "rule_name": decision.rule_name,
                "confidence": decision.confidence,
                "severity": decision.severity,
                "zone": "ZONE_B_INTERSECTION",
                "verified": decision.is_verified,
                "sensor_contributions": temporal_res.get("sensor_contributions", {}),
                "explainable_verdict": " • ".join(decision.explainable_reasoning),
                "evidence_chain": decision.explainable_reasoning,
                "description": "Ambulance acoustic siren verified by Deep Learning Rule Engine (Rule R3).",
                "timestamp": now_iso
            }

        # -------------------------------------------------------------
        # SCENARIO 4: NORMAL TRAFFIC BASELINE
        # -------------------------------------------------------------
        else:
            motion_res = MOTION_TRACKER.update(self._dummy_frame, [[150, 120, 240, 220]], imu_impact_score=0.0)

            accel_val = round(random.uniform(0.01, 0.05), 2)
            temp_val = round(28.5 + temp_noise, 1)
            smoke_val = round(12.0 + smoke_noise, 1)

            decision = DEEP_RULE_ENGINE.evaluate(
                accel_g=accel_val,
                impact_detected=False,
                smoke_ppm=smoke_val,
                temperature_c=temp_val,
                motion_analysis=motion_res,
                scenario_hint="NORMAL"
            )

            telemetry = {
                "temperature": temp_val,
                "smoke_level": smoke_val,
                "impact_detected": False,
                "acceleration_g": accel_val,
                "audio_prediction": {
                    "class": decision.deep_learning["acoustic_model"]["predicted_class"],
                    "confidence": decision.deep_learning["acoustic_model"]["confidence"],
                    "source_file": decision.deep_learning["acoustic_model"]["source"],
                    "dataset": decision.deep_learning["acoustic_model"]["dataset"]
                },
                "vision_prediction": {
                    "class": decision.deep_learning["vision_model"]["primary_class"],
                    "confidence": decision.deep_learning["vision_model"]["confidence"],
                    "hazard": "NONE",
                    "detected_classes": decision.deep_learning["vision_model"]["detected_classes"],
                    "bounding_boxes": decision.deep_learning["vision_model"]["bounding_boxes"],
                    "source_frame": decision.deep_learning["vision_model"]["source"],
                    "dataset": decision.deep_learning["vision_model"]["dataset"]
                },
                "cpu_temp": round(41.5 + temp_noise, 1),
                "fps": 15.2,
                "timestamp": now_iso,
                "motion_analysis": motion_res,
                "rule_id": decision.rule_id,
                "rule_name": decision.rule_name,
                "deep_learning": decision.deep_learning
            }

            temporal_res = TEMPORAL_VERIFIER.ingest_cycle(
                audio_class=telemetry["audio_prediction"]["class"],
                audio_conf=telemetry["audio_prediction"]["confidence"],
                vision_class=telemetry["vision_prediction"]["class"],
                vision_conf=telemetry["vision_prediction"]["confidence"],
                impact_detected=False,
                accel_g=accel_val,
                smoke_ppm=smoke_val,
                temp_c=temp_val
            )

            GREEN_WAVE.reset_corridor()
            MUNICIPAL_GRID.reset_grid()

            actuators = decision.actuators

            active_event = {
                "id": f"ev_norm_{self.cycle_count}",
                "event": decision.event,
                "rule_id": decision.rule_id,
                "rule_name": decision.rule_name,
                "confidence": decision.confidence,
                "severity": decision.severity,
                "zone": "ZONE_B_INTERSECTION",
                "verified": True,
                "sensor_contributions": temporal_res.get("sensor_contributions", {}),
                "explainable_verdict": " • ".join(decision.explainable_reasoning),
                "evidence_chain": decision.explainable_reasoning,
                "description": "Normal urban vehicular traffic evaluated by Deep Learning Rule Engine (Rule R0).",
                "timestamp": now_iso
            }

        # Scenario countdown timer
        if self.scenario_timer > 0:
            self.scenario_timer -= 1
            if self.scenario_timer == 0 and self.active_scenario != "NORMAL":
                LOGGER.info("Scenario duration completed. Returning to NORMAL traffic baseline.")
                self.active_scenario = "NORMAL"

        # Broadcast to Firebase Realtime Database
        FIREBASE_SYNC.sync_live_telemetry(telemetry)
        FIREBASE_SYNC.sync_actuators(actuators)
        FIREBASE_SYNC.sync_emergency_event(active_event)

        state = FIREBASE_SYNC.get_full_live_state()
        state["active_alerts"] = ALERT_MANAGER.get_latest_alerts(limit=5)
        state["recordings"] = DVR.list_recordings()[:5]
        state["grid"] = MUNICIPAL_GRID.get_grid_state()
        state["near_miss"] = telemetry.get("near_miss_analysis") or NEAR_MISS_ANALYZER.evaluate_trajectories([])
        return state

    def _run_loop(self):
        """Continuous execution loop."""
        while self.is_running:
            try:
                self._generate_and_sync_cycle()
            except Exception as e:
                LOGGER.error(f"Error in telemetry loop: {e}")
            time.sleep(self.interval_sec)


# Global singleton instance
STREAMER = LiveEdgeStreamer(interval_sec=1.5)
