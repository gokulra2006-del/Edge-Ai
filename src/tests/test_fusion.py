"""
Unit tests for Module 4: Sensor Fusion.
"""
import unittest
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.modules.sensor_fusion.fusion_engine import SensorFusionEngine
from src.modules.sensors.simulator import SimulatedSensorHub


class TestSensorFusion(unittest.TestCase):
    def setUp(self):
        self.hub = SimulatedSensorHub()
        self.fusion = SensorFusionEngine()

    def test_user_prompt_accident_fusion(self):
        """
        User Prompt:
        audio: crash (0.87), vision: vehicle (0.91), imu: impact (1.0), temp: 32.5, smoke: 120
        Expected: event = "ACCIDENT", confidence > 0.85, verified = True
        """
        packet = self.hub.generate_packet(
            audio_class="crash",
            audio_conf=0.87,
            vision_class="vehicle",
            vision_conf=0.91,
            imu_impact=True,
            imu_g=4.0,
            temp_c=32.5,
            smoke_ppm=120.0
        )
        fused = self.fusion.fuse(packet)

        self.assertEqual(fused.event_type, "ACCIDENT")
        self.assertTrue(fused.is_verified)
        self.assertGreaterEqual(fused.confidence, 0.85)
        self.assertIn("audio", fused.contributing_modalities)
        self.assertIn("imu", fused.contributing_modalities)
        self.assertIn("vision", fused.contributing_modalities)

    def test_single_sensor_false_positive_suppression(self):
        """
        Camera sees vehicle, but audio is normal and IMU is flat.
        Should NOT trigger accident.
        """
        packet = self.hub.generate_packet(
            audio_class="traffic",
            audio_conf=0.90,
            vision_class="vehicle",
            vision_conf=0.95,
            imu_impact=False
        )
        fused = self.fusion.fuse(packet)
        self.assertEqual(fused.event_type, "NORMAL")

    def test_emergency_siren_fusion(self):
        packet = self.hub.generate_packet(
            audio_class="ambulance",
            audio_conf=0.95,
            vision_class="vehicle",
            vision_conf=0.85
        )
        fused = self.fusion.fuse(packet)
        self.assertEqual(fused.event_type, "EMERGENCY_VEHICLE")
        self.assertTrue(fused.is_verified)


if __name__ == "__main__":
    unittest.main()
