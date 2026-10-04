"""
Automated Test Suite for simulation_v1.py.
Validates all 5 predefined scenarios and sensor fusion rules.
"""
import unittest
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from simulation_v1 import SimulatedSensors, EdgeSensorFusion, SimulationLogger


class TestSimulationV1(unittest.TestCase):
    def setUp(self):
        self.fusion = EdgeSensorFusion()

    def test_scenario_1_normal_traffic(self):
        s = SimulatedSensors(
            audio_class="traffic",
            audio_confidence=0.90,
            vision_class="vehicle",
            vision_confidence=0.85,
            imu_impact=False,
            imu_g_force=1.0,
            temperature_c=28.0,
            smoke_ppm=10.0
        )
        r = self.fusion.fuse_and_classify(s)
        self.assertEqual(r.event, "NORMAL")
        self.assertEqual(r.severity, "LOW")
        self.assertEqual(r.response.traffic_signal, "GREEN")
        self.assertEqual(r.response.barrier_gate, "OPEN")
        self.assertEqual(r.response.buzzer_alarm, "OFF")

    def test_scenario_2_accident(self):
        s = SimulatedSensors(
            audio_class="crash",
            audio_confidence=0.87,
            vision_class="vehicle",
            vision_confidence=0.91,
            imu_impact=True,
            imu_g_force=4.2,
            temperature_c=32.5,
            smoke_ppm=25.0
        )
        r = self.fusion.fuse_and_classify(s)
        self.assertEqual(r.event, "ACCIDENT")
        self.assertEqual(r.severity, "CRITICAL")
        self.assertGreaterEqual(r.confidence, 0.90)
        self.assertEqual(r.response.traffic_signal, "RED")
        self.assertEqual(r.response.barrier_gate, "CLOSED")
        self.assertEqual(r.response.buzzer_alarm, "ON")

    def test_scenario_3_fire(self):
        s = SimulatedSensors(
            audio_class="traffic",
            audio_confidence=0.50,
            vision_class="fire",
            vision_confidence=0.89,
            imu_impact=False,
            imu_g_force=1.0,
            temperature_c=68.5,
            smoke_ppm=240.0
        )
        r = self.fusion.fuse_and_classify(s)
        self.assertEqual(r.event, "FIRE")
        self.assertEqual(r.severity, "CRITICAL")
        self.assertEqual(r.response.traffic_signal, "RED")
        self.assertEqual(r.response.barrier_gate, "CLOSED")
        self.assertEqual(r.response.buzzer_alarm, "ON")

    def test_scenario_4_emergency_vehicle(self):
        s = SimulatedSensors(
            audio_class="siren",
            audio_confidence=0.95,
            vision_class="vehicle",
            vision_confidence=0.88,
            imu_impact=False,
            imu_g_force=1.0,
            temperature_c=29.0,
            smoke_ppm=15.0
        )
        r = self.fusion.fuse_and_classify(s)
        self.assertEqual(r.event, "EMERGENCY_VEHICLE")
        self.assertEqual(r.severity, "HIGH")
        self.assertEqual(r.response.traffic_signal, "GREEN (CORRIDOR)")
        self.assertEqual(r.response.barrier_gate, "OPEN")
        self.assertEqual(r.response.buzzer_alarm, "OFF")

    def test_scenario_5_false_alarm_horn_suppressed(self):
        s = SimulatedSensors(
            audio_class="horn",
            audio_confidence=0.92,
            vision_class="vehicle",
            vision_confidence=0.80,
            imu_impact=False,
            imu_g_force=1.0,
            temperature_c=29.5,
            smoke_ppm=12.0
        )
        r = self.fusion.fuse_and_classify(s)
        self.assertEqual(r.event, "NORMAL")
        self.assertEqual(r.severity, "LOW")
        self.assertEqual(r.response.traffic_signal, "GREEN")
        self.assertEqual(r.response.barrier_gate, "OPEN")
        self.assertEqual(r.response.buzzer_alarm, "OFF")


if __name__ == "__main__":
    unittest.main()
