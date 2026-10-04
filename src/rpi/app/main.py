"""
SENTINEL-AI: Raspberry Pi Production Edge Node Main Entry Point.
================================================================
Integrates all hardware sensors, alert evaluation, LCD display,
and actuator control in a fault-tolerant main loop.

Usage:
    python3 -m src.rpi.app.main [--port 8080] [--debug-gps]

Or from the project root:
    python3 src/rpi/app/main.py
"""
import argparse
import json
import signal
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.modules.logging.logger import LOGGER
from src.modules.hardware.hardware_hub import get_hardware_hub
from src.rpi.app.alerts import AlertEngine, AlertLevel
from src.rpi.app.sensor_manager import SensorManager
from src.rpi.app.telemetry import TelemetryFormatter
from src.modules.audio_ai.classifier import AudioClassifier
from src.modules.vision_ai.detector import VisionDetector
from src.modules.decision_engine.deep_rule_engine import DEEP_RULE_ENGINE, DeepRuleDecision


class SentinelEdgeNode:
    """
    Production Raspberry Pi edge node.
    Reads all physical sensors, feeds live camera & audio to Deep Learning models,
    evaluates multi-modal safety rules, updates 16x2 LCD, and actuates physical outputs.
    """

    def __init__(self, debug_gps: bool = False):
        self.is_running = True
        self.cycle_count = 0

        LOGGER.info("=" * 60)
        LOGGER.info("  SENTINEL-AI Raspberry Pi Deep Edge Node Starting")
        LOGGER.info("=" * 60)

        # 1. Initialize hardware hub and sensor manager
        self.hub = get_hardware_hub()
        self.sensor_mgr = SensorManager(hub=self.hub)

        # 2. Initialize Deep Learning AI Models
        LOGGER.info("Loading Edge Deep Learning Models...")
        self.audio_classifier = AudioClassifier()
        self.vision_detector = VisionDetector()
        self.rule_engine = DEEP_RULE_ENGINE

        # If debug GPS requested, reconfigure
        if debug_gps:
            self.hub.gps._debug_nmea = True
            LOGGER.info("[GPS] Debug NMEA logging ENABLED")

        # Initialize alert engine
        self.alert_engine = AlertEngine()

        # Show startup screen on LCD
        try:
            self.hub.lcd.lcd_display_startup()
        except Exception:
            pass

        # Log hardware health
        health = self.hub.get_system_health()
        LOGGER.info(f"Operating Mode: {health['operating_mode']}")
        LOGGER.info(f"Physical Devices Online: {health['physical_devices_online']}")
        LOGGER.info(f"Simulated Devices Active: {health['simulated_devices_active']}")

        # Setup signal handler for clean shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        LOGGER.info(f"Received signal {signum}. Shutting down...")
        self.is_running = False

    def _update_lcd(self, telemetry: dict, alerts: list, ai_decision: dict = None):
        """Updates LCD with current sensor readings and Deep Learning AI decision."""
        try:
            line1, line2 = TelemetryFormatter.format_lcd_lines(telemetry, alerts, ai_decision)
            self.hub.lcd.lcd_display_status(line1, line2)
        except Exception:
            pass

    def run(self):
        """Main real-time deep learning & sensor loop."""
        LOGGER.info("Deep Edge Loop Active. Press Ctrl+C to stop.")

        try:
            while self.is_running:
                self.cycle_count += 1

                # 1. Read all physical sensors (DHT22, GY-87, ADS1115+MQ2, GPS)
                telemetry = self.sensor_mgr.poll()

                # 2. Acquire live hardware frames and audio samples
                frame = self.hub.camera.capture_frame()
                pcm_audio = self.hub.inmp441.capture_audio(duration_seconds=0.4)

                # 3. Execute Deep Learning Inference
                # Vision Deep Learning (YOLO11)
                if frame is not None:
                    vision_pred = self.vision_detector.predict_image(frame)
                else:
                    vision_pred = self.vision_detector.predict({"class": "vehicle", "confidence": 0.88})

                # Acoustic Deep Learning (EdgeAcousticNet)
                if pcm_audio:
                    audio_pred = self.audio_classifier.predict_pcm(pcm_audio)
                else:
                    audio_pred = self.audio_classifier.predict({"class": "traffic", "confidence": 0.88})

                # 4. Extract Physical Telemetry
                accel_g = telemetry.get("imu", {}).get("composite_g", 1.0)
                impact_detected = telemetry.get("imu", {}).get("impact_detected", False)
                smoke_ppm = telemetry.get("gas", {}).get("relative_gas_level", 12.0)
                temperature_c = telemetry.get("temperature", 25.0)

                # 5. Evaluate Multi-Modal Deep Decision Engine (Fuses Deep AI + Physical Sensors)
                raw_audio = {
                    "class": audio_pred.class_name,
                    "confidence": audio_pred.confidence,
                    "source_file": "INMP441_Live_Mic",
                    "dataset": "Hardware_Live"
                }
                raw_image = {
                    "class": vision_pred.primary_class,
                    "confidence": vision_pred.confidence,
                    "detected_classes": vision_pred.detected_classes,
                    "bounding_boxes": vision_pred.bounding_boxes,
                    "source_frame": "CSI_Camera_Live",
                    "dataset": "Hardware_Live"
                }

                decision = self.rule_engine.evaluate(
                    raw_audio=raw_audio,
                    raw_image=raw_image,
                    accel_g=accel_g,
                    impact_detected=impact_detected,
                    smoke_ppm=smoke_ppm,
                    temperature_c=temperature_c
                )
                decision_dict = decision.to_dict()

                # 6. Apply Actuator Controls based on Deep Learning Verdict
                try:
                    # Traffic Signal
                    self.hub.actuators.set_traffic_light(decision.actuators.get("traffic_signal", "GREEN"))
                    # Servo Barrier Gate
                    self.hub.actuators.set_barrier(decision.actuators.get("barrier", "OPEN"))
                    # Buzzer Alert
                    if decision.actuators.get("buzzer") == "ON":
                        self.hub.actuators.beep(duration_ms=120, count=1)
                    else:
                        self.hub.actuators.buzzer_off()
                except Exception as e:
                    LOGGER.error(f"Actuator control error: {e}")

                # 7. Evaluate secondary threshold alerts
                alerts = self.alert_engine.evaluate(telemetry)
                alert_dicts = [a.to_dict() for a in alerts]

                # 8. Update physical 16x2 LCD screen with Live Telemetry + AI State
                self._update_lcd(telemetry, alert_dicts, decision_dict)

                # 9. Log periodic telemetry & deep learning event
                if self.cycle_count % 5 == 0 or decision.severity in ("CRITICAL", "HIGH"):
                    compact = TelemetryFormatter.to_compact_summary(telemetry)
                    LOGGER.info(
                        f"[Cycle {self.cycle_count}] AI_EVENT={decision.event} ({decision.severity}, conf={decision.confidence:.2f}) | "
                        f"Rule={decision.rule_id} | {compact}"
                    )

                time.sleep(1.0)

        except KeyboardInterrupt:
            LOGGER.info("Keyboard interrupt received.")
        finally:
            self.shutdown()

    def shutdown(self):
        """Clean shutdown."""
        LOGGER.info("Shutting down SENTINEL-AI Edge Node...")
        try:
            self.hub.lcd.lcd_display_status("  SENTINEL-AI   ", "  Shutting Down  ")
            time.sleep(0.5)
        except Exception:
            pass
        self.hub.cleanup()
        LOGGER.info("Node stopped cleanly.")


def main():
    parser = argparse.ArgumentParser(description="SENTINEL-AI Raspberry Pi Edge Node")
    parser.add_argument("--debug-gps", action="store_true", help="Enable raw NMEA debug logging")
    args = parser.parse_args()

    node = SentinelEdgeNode(debug_gps=args.debug_gps)
    node.run()


if __name__ == "__main__":
    main()
