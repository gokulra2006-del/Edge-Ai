"""
Unit Tests for Sentinel-AI Hardware Abstraction Layer.
=====================================================
Tests hardware configuration, pin registry integrity, mock fallback,
and driver telemetry formatting. Runs cleanly on any development machine.
"""
import unittest
from src.config.hardware_config import HARDWARE_CONFIG
from src.modules.hardware.hardware_hub import HARDWARE_HUB
from src.modules.hardware.base_driver import DriverStatus


class TestHardwareAbstractionLayer(unittest.TestCase):

    def test_pin_registry_integrity(self):
        """Validates that all assigned pins are unique and non-conflicting."""
        errors = HARDWARE_CONFIG.validate_pin_assignments()
        self.assertEqual(len(errors), 0, f"Found GPIO pin conflicts: {errors}")

    def test_user_requested_pins_adherence(self):
        """Asserts that all pins strictly match the user specifications."""
        pins = HARDWARE_CONFIG.PINS
        self.assertEqual(pins["dht22_data"].bcm, 4)
        self.assertEqual(pins["dht22_data"].physical, 7)

        self.assertEqual(pins["i2c_sda"].bcm, 2)
        self.assertEqual(pins["i2c_sda"].physical, 3)

        self.assertEqual(pins["i2c_scl"].bcm, 3)
        self.assertEqual(pins["i2c_scl"].physical, 5)

        self.assertEqual(pins["gps_rx_pi_tx"].bcm, 14)
        self.assertEqual(pins["gps_rx_pi_tx"].physical, 8)

        self.assertEqual(pins["gps_tx_pi_rx"].bcm, 15)
        self.assertEqual(pins["gps_tx_pi_rx"].physical, 10)

        self.assertEqual(pins["inmp441_sck"].bcm, 18)
        self.assertEqual(pins["inmp441_ws"].bcm, 19)
        self.assertEqual(pins["inmp441_sd"].bcm, 20)

        self.assertEqual(pins["led_red"].bcm, 5)
        self.assertEqual(pins["led_yellow"].bcm, 6)
        self.assertEqual(pins["led_green"].bcm, 13)
        self.assertEqual(pins["buzzer"].bcm, 16)
        self.assertEqual(pins["servo_barrier"].bcm, 12)

    def test_dht22_driver_contract(self):
        """DHT-22 driver must return temperature and humidity with simulation flag."""
        reading = HARDWARE_HUB.dht22.read()
        self.assertIn("temperature_c", reading)
        self.assertIn("humidity_pct", reading)
        self.assertIn("quality", reading)
        self.assertIn("is_simulated", reading["quality"])

    def test_gy87_driver_contract(self):
        """GY-87 driver must return 10-DOF telemetry (accel, gyro, compass, baro)."""
        reading = HARDWARE_HUB.gy87.read()
        self.assertIn("accelerometer_g", reading)
        self.assertIn("gyroscope_dps", reading)
        self.assertIn("composite_g", reading)
        self.assertIn("compass_heading_deg", reading)
        self.assertIn("barometric_pressure_hpa", reading)
        self.assertIn("barometric_altitude_m", reading)

    def test_gps_driver_contract(self):
        """NEO-6M driver must return valid coordinates, altitude, and speed."""
        reading = HARDWARE_HUB.gps.read()
        self.assertIn("latitude", reading)
        self.assertIn("longitude", reading)
        self.assertIn("altitude_m", reading)
        self.assertIn("fix_status", reading)

    def test_ads1115_driver_contract(self):
        """ADS1115 driver must return smoke PPM and voltage."""
        reading = HARDWARE_HUB.ads1115.read()
        self.assertIn("raw_adc_voltage", reading)
        self.assertIn("smoke_ppm", reading)
        self.assertIn("hazard_detected", reading)

    def test_actuator_driver_state_machine(self):
        """Actuator driver must safely transition traffic light, barrier, and buzzer."""
        act = HARDWARE_HUB.actuators
        act.set_traffic_light("RED")
        self.assertEqual(act._traffic_state, "RED")

        act.set_barrier("CLOSED")
        self.assertEqual(act._barrier_state, "CLOSED")

        act.set_buzzer(True)
        self.assertTrue(act._buzzer_active)
        act.set_buzzer(False)
        self.assertFalse(act._buzzer_active)

    def test_hardware_hub_system_health(self):
        """HardwareHub must report consolidated health across all 7 drivers."""
        health = HARDWARE_HUB.get_system_health()
        self.assertIn("board", health)
        self.assertIn("operating_mode", health)
        self.assertIn("drivers", health)
        self.assertGreaterEqual(len(health["drivers"]), 7)


if __name__ == "__main__":
    unittest.main()
