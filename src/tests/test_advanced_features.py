"""Unit test suite for the 5 Advanced Software Features:
1. Blackbox Video DVR (Circular Deque + MP4 Encoder)
2. Vehicle Motion Tracker & Optical Flow Deceleration
3. Temporal Multi-Sensor Fusion & Explainable Decision Verification
4. Automated Alert Dispatch Queue & Cooldown System
5. Multi-Node Green Wave Arterial Corridor Routing
"""

import os
import time
import unittest
import numpy as np

from src.modules.recording.blackbox_dvr import BlackboxDVR
from src.modules.vision_ai.motion_tracker import VehicleMotionTracker
from src.modules.sensor_fusion.temporal_verifier import TemporalFusionVerifier
from src.modules.autonomous_response.alert_manager import AlertDispatchManager, EmergencyIncident
from src.modules.autonomous_response.green_wave_coordinator import GreenWaveCoordinator


class TestAdvancedSoftwareFeatures(unittest.TestCase):

    def setUp(self):
        self.dvr = BlackboxDVR(buffer_seconds=2, fps=10, frame_size=(320, 240))
        self.tracker = VehicleMotionTracker(max_history=15, fps=10.0)
        self.verifier = TemporalFusionVerifier(window_size=5, persistence_threshold=2)
        self.alert_mgr = AlertDispatchManager(cooldown_seconds=1)
        self.coordinator = GreenWaveCoordinator(avg_speed_kmh=50.0)

    def tearDown(self):
        self.alert_mgr._is_running = False

    # 1. Test Blackbox Video DVR
    def test_blackbox_dvr_circular_buffer(self):
        dummy_frame = np.zeros((240, 320, 3), dtype=np.uint8)
        for i in range(15):
            self.dvr.add_frame(dummy_frame)

        self.assertGreaterEqual(len(self.dvr._buffer), 10)
        self.assertLessEqual(len(self.dvr._buffer), 20)

    def test_blackbox_dvr_recording_trigger(self):
        dummy_frame = np.ones((240, 320, 3), dtype=np.uint8) * 128
        for i in range(10):
            self.dvr.add_frame(dummy_frame)

        event_id = "TEST_INCIDENT_001"
        fname = self.dvr.trigger_incident_capture(event_id, event_type="TEST_CRASH", post_event_seconds=1)
        self.assertTrue(fname.startswith("incident_TEST_INCIDENT_001"))

        time.sleep(1.2)
        files = self.dvr.list_recordings()
        self.assertIsInstance(files, list)

    # 2. Test Optical Flow & Motion Tracking
    def test_motion_tracker_normal_flow(self):
        frame1 = np.zeros((200, 200, 3), dtype=np.uint8)
        frame2 = np.zeros((200, 200, 3), dtype=np.uint8)

        detections = [[50, 50, 80, 80]]
        res1 = self.tracker.update(frame1, detections)
        self.assertEqual(res1["tracked_vehicle_count"], 1)

        detections2 = [[55, 50, 85, 80]]
        res2 = self.tracker.update(frame2, detections2)
        self.assertLess(res2["composite_crash_score"], 0.65)
        self.assertFalse(res2["crash_visually_confirmed"])

    def test_motion_tracker_sudden_deceleration(self):
        f1 = np.zeros((200, 200, 3), dtype=np.uint8)
        self.tracker.update(f1, [[20, 20, 40, 40]])
        f2 = np.zeros((200, 200, 3), dtype=np.uint8)
        self.tracker.update(f2, [[60, 20, 80, 40]])

        # Overlapping collision scenario with high impact
        f3 = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        res = self.tracker.update(f3, [[60, 20, 80, 40], [65, 22, 85, 42]], imu_impact_score=1.0)
        self.assertGreater(res["composite_crash_score"], 0.0)

    # 3. Test Temporal Multi-Sensor Fusion Verifier
    def test_temporal_fusion_persistence_verification(self):
        v1 = self.verifier.ingest_cycle(
            audio_class="crash",
            audio_conf=0.90,
            vision_class="vehicle",
            vision_conf=0.88,
            impact_detected=True,
            accel_g=4.2,
            smoke_ppm=15.0,
            temp_c=30.0,
            crash_motion_score=0.75
        )
        self.assertEqual(v1["event"], "ACCIDENT")
        self.assertFalse(v1["is_verified"])

        v2 = self.verifier.ingest_cycle(
            audio_class="crash",
            audio_conf=0.92,
            vision_class="vehicle",
            vision_conf=0.85,
            impact_detected=True,
            accel_g=4.5,
            smoke_ppm=16.0,
            temp_c=30.2,
            crash_motion_score=0.80
        )
        self.assertTrue(v2["is_verified"])
        self.assertEqual(v2["event"], "ACCIDENT")
        self.assertGreater(len(v2["evidence_chain"]), 0)

    def test_temporal_fusion_suppresses_transient_glitch(self):
        self.verifier.ingest_cycle(
            audio_class="traffic",
            audio_conf=0.50,
            vision_class="fire",
            vision_conf=0.75,
            impact_detected=False,
            accel_g=0.05,
            smoke_ppm=90.0,
            temp_c=60.0
        )

        res = self.verifier.ingest_cycle(
            audio_class="traffic",
            audio_conf=0.95,
            vision_class="vehicle",
            vision_conf=0.90,
            impact_detected=False,
            accel_g=0.03,
            smoke_ppm=12.0,
            temp_c=28.0
        )
        self.assertEqual(res["event"], "NORMAL")

    # 4. Test Automated Alert Dispatch Queue & Cooldown
    def test_alert_manager_queue_and_cooldown(self):
        alert_dispatched = self.alert_mgr.post_incident(
            incident_id="INC-001",
            event_type="ACCIDENT",
            severity="CRITICAL",
            confidence=0.95,
            zone="NODE_B_INTERSECTION",
            evidence=["Audio crash", "Shock spike"],
            actions=["RED signal", "Barrier closed"]
        )
        self.assertIsNotNone(alert_dispatched)
        self.assertEqual(alert_dispatched.event_type, "ACCIDENT")

        # Immediate re-trigger should be throttled
        duplicate = self.alert_mgr.post_incident(
            incident_id="INC-002",
            event_type="ACCIDENT",
            severity="CRITICAL",
            confidence=0.95,
            zone="NODE_B_INTERSECTION",
            evidence=["Audio crash"],
            actions=["RED signal"]
        )
        self.assertIsNone(duplicate)

    def test_alert_manager_acknowledgment(self):
        alert = self.alert_mgr.post_incident(
            incident_id="INC-FIRE-99",
            event_type="FIRE",
            severity="CRITICAL",
            confidence=0.93,
            zone="NODE_B_INTERSECTION",
            evidence=["Smoke > 150ppm"],
            actions=["Barrier closed"]
        )
        self.assertIsNotNone(alert)
        ack_success = self.alert_mgr.acknowledge_incident("INC-FIRE-99", operator_name="OPERATOR_OFFICER_4")
        self.assertTrue(ack_success)
        self.assertEqual(alert.status, "ACKNOWLEDGED")
        self.assertEqual(alert.acknowledged_by, "OPERATOR_OFFICER_4")

    # 5. Test Multi-Node Green Wave Arterial Routing
    def test_green_wave_corridor_activation(self):
        plan = self.coordinator.initiate_green_wave(
            origin_node="NODE_A",
            target_destination="NODE_D",
            priority_level="CRITICAL"
        )
        self.assertEqual(plan["origin_node"], "NODE_A")
        self.assertEqual(plan["destination_node"], "NODE_D")
        self.assertEqual(len(plan["route_nodes"]), 4)

        etas = [node["eta_seconds"] for node in plan["route_nodes"]]
        self.assertTrue(all(etas[i] <= etas[i + 1] for i in range(len(etas) - 1)))

        status = self.coordinator.get_corridor_status()
        self.assertTrue(status["corridor_active"])

        self.coordinator.reset_corridor()
        status_after = self.coordinator.get_corridor_status()
        self.assertFalse(status_after["corridor_active"])

if __name__ == "__main__":
    unittest.main()
