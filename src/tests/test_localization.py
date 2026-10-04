"""
Unit tests for Module 6: Localization.
"""
import unittest
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.modules.localization.localizer import MultiNodeLocalizer
from src.modules.sensor_fusion.fusion_engine import SensorFusionEngine
from src.modules.sensors.simulator import SimulatedSensorHub


class TestLocalization(unittest.TestCase):
    def setUp(self):
        self.localizer = MultiNodeLocalizer()
        self.hub = SimulatedSensorHub()
        self.fusion = SensorFusionEngine()

    def test_slide8_localization_scenario(self):
        """Matches project presentation Slide 8 matrix."""
        packet = self.hub.scenario_accident()
        fused = self.fusion.fuse(packet)

        # Node matrix from presentation: A: 62%, B: 94%, C: 76%, D: 31%
        matrix = {"NODE_A": 0.62, "NODE_B": 0.94, "NODE_C": 0.76, "NODE_D": 0.31}
        location = self.localizer.estimate_location(fused, node_confidence_matrix=matrix)

        self.assertEqual(location.primary_node, "NODE_B")
        self.assertEqual(location.probable_zone, "ZONE_B_INTERSECTION")
        self.assertEqual(location.zone_confidence, 0.94)


if __name__ == "__main__":
    unittest.main()
