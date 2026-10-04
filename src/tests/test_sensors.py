"""
Unit tests for Module 1: Sensors.
"""
import unittest
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.modules.sensors.simulator import SimulatedSensorHub


class TestSensors(unittest.TestCase):
    def setUp(self):
        self.hub = SimulatedSensorHub(node_id="NODE_TEST")

    def test_generate_custom_packet(self):
        packet = self.hub.generate_packet(
            audio_class="crash",
            audio_conf=0.87,
            vision_class="vehicle",
            vision_conf=0.91,
            imu_impact=True,
            temp_c=32.5,
            smoke_ppm=120.0
        )
        self.assertEqual(packet.node_id, "NODE_TEST")
        self.assertEqual(packet.audio_prediction.class_name, "crash")
        self.assertEqual(packet.audio_prediction.confidence, 0.87)
        self.assertTrue(packet.imu_reading.impact_detected)
        self.assertEqual(packet.environment.temperature_c, 32.5)

    def test_preset_accident_scenario(self):
        packet = self.hub.scenario_accident()
        self.assertEqual(packet.audio_prediction.class_name, "crash")
        self.assertTrue(packet.imu_reading.impact_detected)


if __name__ == "__main__":
    unittest.main()
