"""
SENTINEL-AI: Sensor Manager & Fault Isolation Layer.
=====================================================
Orchestrates sensor sampling, tracks per-sensor error rates and recovery,
and provides thread-safe access to latest unified telemetry snapshots.
"""
import logging
import threading
import time
from typing import Any, Dict, Optional
from src.modules.hardware.hardware_hub import HardwareHub, get_hardware_hub

logger = logging.getLogger("EdgeAI")


class SensorManager:
    """
    Manages sensor polling cycles, error rate isolation, and thread-safe
    telemetry dissemination for the Raspberry Pi edge node.
    """

    def __init__(self, hub: Optional[HardwareHub] = None):
        self.hub = hub or get_hardware_hub()
        self._lock = threading.Lock()
        self._latest_telemetry: Dict[str, Any] = {}
        self._polling_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._poll_count = 0
        self._error_counts: Dict[str, int] = {
            "dht22": 0, "gy87": 0, "mq2": 0, "gps": 0, "inmp441": 0, "camera": 0
        }

        # Perform initial poll
        self.poll()

    def poll(self) -> Dict[str, Any]:
        """
        Polls all sensors via HardwareHub, isolates any individual exceptions,
        updates internal health counters, and caches the latest snapshot.
        """
        self._poll_count += 1
        try:
            telemetry = self.hub.get_unified_telemetry()
        except Exception as e:
            logger.error(f"[SensorManager] Critical error in telemetry collection: {e}")
            telemetry = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "status": "CRITICAL_ERROR",
                "error": str(e)
            }

        # Update per-sensor error tracking based on status flags
        self._track_sensor_health(telemetry)

        with self._lock:
            self._latest_telemetry = telemetry

        return telemetry

    def _track_sensor_health(self, telemetry: Dict[str, Any]):
        """Tracks error tallies per sensor based on telemetry results."""
        if telemetry.get("temperature") is None:
            self._error_counts["dht22"] += 1

        imu_status = telemetry.get("imu", {}).get("status")
        if imu_status in ("ERROR", "OFFLINE"):
            self._error_counts["gy87"] += 1

        gas_status = telemetry.get("gas", {}).get("status")
        if gas_status in ("ERROR", "OFFLINE"):
            self._error_counts["mq2"] += 1

        gps_status = telemetry.get("gps", {}).get("status")
        if gps_status in ("ERROR", "OFFLINE"):
            self._error_counts["gps"] += 1

        audio_status = telemetry.get("audio", {}).get("status")
        if audio_status in ("ERROR", "OFFLINE"):
            self._error_counts["inmp441"] += 1

    def get_latest_telemetry(self) -> Dict[str, Any]:
        """Returns the most recent cached telemetry snapshot thread-safely."""
        with self._lock:
            return dict(self._latest_telemetry)

    def get_metrics(self) -> Dict[str, Any]:
        """Returns polling counts and error metrics."""
        return {
            "total_polls": self._poll_count,
            "errors": dict(self._error_counts),
            "health": self.hub.get_system_health()
        }

    def start_background_polling(self, interval_seconds: float = 1.0):
        """Starts asynchronous background polling thread."""
        if self._polling_thread and self._polling_thread.is_alive():
            logger.warning("[SensorManager] Background polling already running.")
            return

        self._stop_event.clear()
        self._polling_thread = threading.Thread(
            target=self._background_loop,
            args=(interval_seconds,),
            daemon=True,
            name="SensorManager-Poller"
        )
        self._polling_thread.start()
        logger.info(f"[SensorManager] Background polling started (interval={interval_seconds}s)")

    def stop_background_polling(self):
        """Stops asynchronous background polling thread."""
        if self._polling_thread and self._polling_thread.is_alive():
            self._stop_event.set()
            self._polling_thread.join(timeout=3.0)
            logger.info("[SensorManager] Background polling stopped.")

    def _background_loop(self, interval_seconds: float):
        while not self._stop_event.is_set():
            self.poll()
            self._stop_event.wait(interval_seconds)

    def cleanup(self):
        """Stops background thread and cleans up all hardware resources."""
        self.stop_background_polling()
        self.hub.cleanup()
