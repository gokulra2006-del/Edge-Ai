"""
Unit tests for Module 9: Web Dashboard & Firebase Cloud Synchronization.
"""
import unittest
import json
from src.modules.dashboard.firebase_sync import FirebaseEdgeSync
from src.modules.dashboard.live_streamer import LiveEdgeStreamer


class TestDashboardFirebase(unittest.TestCase):

    def setUp(self):
        self.fb = FirebaseEdgeSync(database_url="", node_id="TEST_NODE")
        self.streamer = LiveEdgeStreamer(interval_sec=0.1)

    def test_firebase_config_and_url_builder(self):
        self.assertFalse(self.fb.is_configured())
        self.fb.set_config("https://test-project-default-rtdb.firebaseio.com", "test-secret")
        self.assertTrue(self.fb.is_configured())

        url = self.fb._build_url("nodes/TEST_NODE/telemetry")
        self.assertEqual(url, "https://test-project-default-rtdb.firebaseio.com/nodes/TEST_NODE/telemetry.json?auth=test-secret")

    def test_local_cache_telemetry_sync(self):
        # Even without cloud credentials, local cache should update smoothly
        telemetry = {"temperature": 29.5, "smoke_level": 15.0, "impact_detected": False}
        self.fb.sync_live_telemetry(telemetry)

        state = self.fb.get_full_live_state()
        self.assertEqual(state["telemetry"]["temperature"], 29.5)
        self.assertEqual(state["telemetry"]["smoke_level"], 15.0)

    def test_scenario_trigger_cycle_generation(self):
        # Test Accident scenario
        acc_state = self.streamer.trigger_scenario("ACCIDENT")
        self.assertEqual(acc_state["active_event"]["event"], "ACCIDENT")
        self.assertEqual(acc_state["actuators"]["traffic_signal"], "RED")
        self.assertEqual(acc_state["actuators"]["barrier"], "CLOSED")
        self.assertEqual(acc_state["actuators"]["buzzer"], "ON")

        # Test Fire scenario
        fire_state = self.streamer.trigger_scenario("FIRE")
        self.assertEqual(fire_state["active_event"]["event"], "FIRE")
        self.assertGreater(fire_state["telemetry"]["temperature"], 50.0)

        # Test Ambulance corridor scenario
        amb_state = self.streamer.trigger_scenario("AMBULANCE")
        self.assertEqual(amb_state["active_event"]["event"], "EMERGENCY_VEHICLE")
        self.assertTrue(amb_state["actuators"]["green_corridor_active"])

        # Test Normal reset
        norm_state = self.streamer.trigger_scenario("NORMAL")
        self.assertEqual(norm_state["active_event"]["event"], "NORMAL")
        self.assertEqual(norm_state["actuators"]["traffic_signal"], "GREEN")


if __name__ == "__main__":
    unittest.main()
