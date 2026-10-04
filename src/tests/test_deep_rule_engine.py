"""
Unit Tests for DeepInferenceRuleEngine.
Verifies raw input handling, trained deep learning model queries,
and deterministic safety rule activation.
"""
import unittest
from src.modules.decision_engine.deep_rule_engine import DEEP_RULE_ENGINE, DeepRuleDecision


class TestDeepInferenceRuleEngine(unittest.TestCase):

    def setUp(self):
        self.engine = DEEP_RULE_ENGINE

    def test_rule_catalog_integrity(self):
        """Rule catalog must declare all primary safety rules."""
        catalog = self.engine.get_rule_catalog()
        self.assertGreaterEqual(len(catalog), 5)
        rule_ids = [r["rule_id"] for r in catalog]
        self.assertIn("RULE_R1_COLLISION", rule_ids)
        self.assertIn("RULE_R2_FIRE_SMOKE", rule_ids)
        self.assertIn("RULE_R3_EMERGENCY_CORRIDOR", rule_ids)
        self.assertIn("RULE_R4_NEAR_MISS", rule_ids)
        self.assertIn("RULE_R0_NOMINAL", rule_ids)

    def test_rule_r1_collision_activation(self):
        """Rule R1 should trigger on crash audio + physical impact shock."""
        decision = self.engine.evaluate(
            raw_audio={"class": "crash_impact", "confidence": 0.88, "source_file": "174290-6-3-0.wav", "dataset": "UrbanSound8K"},
            accel_g=5.4,
            impact_detected=True,
            smoke_ppm=25.0,
            temperature_c=30.0
        )
        self.assertIsInstance(decision, DeepRuleDecision)
        self.assertEqual(decision.rule_id, "RULE_R1_COLLISION")
        self.assertEqual(decision.event, "ACCIDENT")
        self.assertEqual(decision.severity, "CRITICAL")
        self.assertTrue(decision.is_verified)
        self.assertEqual(decision.actuators["traffic_signal"], "RED")
        self.assertEqual(decision.actuators["barrier"], "CLOSED")
        self.assertIn("EdgeAcousticNet", decision.deep_learning["acoustic_model"]["model"])

    def test_rule_r2_fire_smoke_activation(self):
        """Rule R2 should trigger on YOLO Fire detection + toxic smoke density."""
        decision = self.engine.evaluate(
            raw_image={"class": "Fire", "confidence": 0.85, "detected_classes": ["Fire"], "bounding_boxes": [], "source_frame": "frame_fire.jpg", "dataset": "FIRE_n_SMOKE"},
            accel_g=0.03,
            impact_detected=False,
            smoke_ppm=210.0,
            temperature_c=74.0
        )
        self.assertEqual(decision.rule_id, "RULE_R2_FIRE_SMOKE")
        self.assertEqual(decision.event, "FIRE")
        self.assertEqual(decision.severity, "CRITICAL")
        self.assertTrue(decision.is_verified)
        self.assertEqual(decision.actuators["traffic_signal"], "RED")
        self.assertIn("YOLO11n-Edge", decision.deep_learning["vision_model"]["model"])

    def test_rule_r3_emergency_corridor_activation(self):
        """Rule R3 should trigger on siren audio with high confidence."""
        decision = self.engine.evaluate(
            raw_audio={"class": "ambulance", "confidence": 0.94, "source_file": "sound_43.wav", "dataset": "sireNNet"},
            accel_g=0.02,
            impact_detected=False,
            smoke_ppm=14.0,
            temperature_c=27.0
        )
        self.assertEqual(decision.rule_id, "RULE_R3_EMERGENCY_CORRIDOR")
        self.assertEqual(decision.event, "EMERGENCY_VEHICLE")
        self.assertEqual(decision.severity, "HIGH")
        self.assertTrue(decision.actuators["green_corridor_active"])
        self.assertEqual(decision.actuators["traffic_signal"], "GREEN")

    def test_rule_r0_nominal_baseline(self):
        """Rule R0 should trigger when all inputs remain nominal."""
        decision = self.engine.evaluate(
            raw_audio={"class": "traffic", "confidence": 0.92, "source_file": "traffic_amb.wav", "dataset": "UrbanSound8K"},
            raw_image={"class": "vehicle", "confidence": 0.88, "detected_classes": ["vehicle"], "source_frame": "traffic.jpg", "dataset": "vehicles_yolo11"},
            accel_g=0.02,
            impact_detected=False,
            smoke_ppm=12.0,
            temperature_c=28.0
        )
        self.assertEqual(decision.rule_id, "RULE_R0_NOMINAL")
        self.assertEqual(decision.event, "NORMAL")
        self.assertEqual(decision.severity, "LOW")
    def test_rule_r5_vehicle_smoke_suppression(self):
        """Rule R5 should detect vehicle exhaust / car smoke and avoid triggering emergency fire sirens."""
        decision = self.engine.evaluate(
            raw_image={
                "class": "Smoke",
                "confidence": 0.82,
                "detected_classes": ["Smoke", "car"],
                "source_frame": "car_tailpipe.jpg",
                "dataset": "vehicles_yolo11"
            },
            accel_g=0.03,
            impact_detected=False,
            smoke_ppm=22.0,  # Below 70 PPM threshold (normal exhaust)
            temperature_c=29.0  # Below 48C threshold (ambient)
        )
        self.assertEqual(decision.rule_id, "RULE_R5_VEHICLE_SMOKE")
        self.assertEqual(decision.event, "VEHICLE_SMOKE")
        self.assertEqual(decision.severity, "LOW")
        self.assertEqual(decision.actuators["traffic_signal"], "GREEN")
        self.assertEqual(decision.actuators["barrier"], "OPEN")
        self.assertEqual(decision.actuators["buzzer"], "OFF")


if __name__ == "__main__":
    unittest.main()
