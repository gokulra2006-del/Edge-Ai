"""
Unit tests for Module 5: Severity Assessment.
"""
import unittest
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.modules.severity_assessment.evaluator import SeverityEvaluator
from src.modules.sensor_fusion.fusion_engine import SensorFusionEngine
from src.modules.sensors.simulator import SimulatedSensorHub


class TestSeverity(unittest.TestCase):
    def setUp(self):
        self.hub = SimulatedSensorHub()
        self.fusion = SensorFusionEngine()
        self.severity = SeverityEvaluator()

    def test_accident_critical_severity(self):
        packet = self.hub.scenario_accident()
        fused = self.fusion.fuse(packet)
        assessment = self.severity.evaluate(fused)
        self.assertEqual(assessment.level, "CRITICAL")
        self.assertGreaterEqual(assessment.score, 0.80)

    def test_normal_low_severity(self):
        packet = self.hub.scenario_normal_traffic()
        fused = self.fusion.fuse(packet)
        assessment = self.severity.evaluate(fused)
        self.assertEqual(assessment.level, "LOW")


if __name__ == "__main__":
    unittest.main()
