"""
Integration tests for the complete Edge-AI emergency pipeline.
"""
import unittest
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.core.orchestrator import EmergencyPipelineOrchestrator
from src.modules.sensors.simulator import SimulatedSensorHub


class TestIntegrationPipeline(unittest.TestCase):
    def setUp(self):
        self.orchestrator = EmergencyPipelineOrchestrator()
        self.hub = SimulatedSensorHub()

    def test_full_accident_pipeline_flow(self):
        packet = self.hub.generate_packet(
            audio_class="crash",
            audio_conf=0.87,
            vision_class="vehicle",
            vision_conf=0.91,
            imu_impact=True,
            temp_c=32.5,
            smoke_ppm=120.0
        )
        result = self.orchestrator.process_packet(
            packet,
            node_confidence_matrix={"NODE_A": 0.62, "NODE_B": 0.94, "NODE_C": 0.76, "NODE_D": 0.31}
        )

        self.assertEqual(result["event"], "ACCIDENT")
        self.assertGreaterEqual(result["confidence"], 0.85)
        self.assertTrue(result["is_verified"])
        self.assertEqual(result["severity"], "CRITICAL")
        self.assertEqual(result["location"], "ZONE_B_INTERSECTION")
        self.assertIn("RESTRICT", result["action"])

    def test_full_green_corridor_pipeline_flow(self):
        packet = self.hub.scenario_emergency_siren()
        result = self.orchestrator.process_packet(packet)

        self.assertEqual(result["event"], "EMERGENCY_VEHICLE")
        self.assertTrue(result["green_corridor"])
        self.assertIn("GREEN_CORRIDOR", result["action"])


if __name__ == "__main__":
    unittest.main()
