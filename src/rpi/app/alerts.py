"""
SENTINEL-AI: Configurable Alert Engine.
========================================
Evaluates sensor telemetry against configurable thresholds.
Triggers LED, buzzer, and servo actions when alerts fire.

All thresholds come from HARDWARE_CONFIG.ALERT_THRESHOLDS and can be
overridden via hardware.json. No hardcoded values.
"""
import logging
import time
from typing import Any, Dict, List
from src.config.hardware_config import HARDWARE_CONFIG

logger = logging.getLogger("EdgeAI")


class AlertLevel:
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class Alert:
    """Represents a single triggered alert."""
    def __init__(self, level: str, source: str, message: str, value: float = 0.0):
        self.level = level
        self.source = source
        self.message = message
        self.value = value
        self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "source": self.source,
            "message": self.message,
            "value": self.value,
            "timestamp": self.timestamp,
        }


class AlertEngine:
    """
    Evaluates telemetry against thresholds and returns active alerts.

    Does NOT directly drive actuators — that is the caller's responsibility.
    This separation prevents dangerous automatic actions.
    """

    def __init__(self):
        self.thresholds = HARDWARE_CONFIG.ALERT_THRESHOLDS
        self._active_alerts: List[Alert] = []

    def evaluate(self, telemetry: Dict[str, Any]) -> List[Alert]:
        """
        Evaluates a unified telemetry dict and returns a list of triggered alerts.
        """
        alerts = []

        # Temperature check
        temp = telemetry.get("temperature")
        if temp is not None:
            if temp >= self.thresholds["high_temperature_c"]:
                alerts.append(Alert(
                    AlertLevel.CRITICAL, "temperature",
                    f"High temperature: {temp}°C (threshold: {self.thresholds['high_temperature_c']}°C)",
                    temp
                ))

        # Humidity check
        humidity = telemetry.get("humidity")
        if humidity is not None:
            if humidity >= self.thresholds["high_humidity_pct"]:
                alerts.append(Alert(
                    AlertLevel.WARNING, "humidity",
                    f"High humidity: {humidity}% (threshold: {self.thresholds['high_humidity_pct']}%)",
                    humidity
                ))

        # Gas/Smoke check (uses voltage, NOT fake PPM)
        gas = telemetry.get("gas", {})
        gas_voltage = gas.get("adc_voltage")
        if gas_voltage is not None and gas.get("is_warm", False):
            if gas_voltage >= self.thresholds["gas_level_critical"]:
                alerts.append(Alert(
                    AlertLevel.CRITICAL, "gas",
                    f"Critical gas level: {gas_voltage}V (threshold: {self.thresholds['gas_level_critical']}V)",
                    gas_voltage
                ))
            elif gas_voltage >= self.thresholds["gas_level_warning"]:
                alerts.append(Alert(
                    AlertLevel.WARNING, "gas",
                    f"Gas warning: {gas_voltage}V (threshold: {self.thresholds['gas_level_warning']}V)",
                    gas_voltage
                ))

        # IMU impact check
        imu = telemetry.get("imu", {})
        composite_g = imu.get("composite_g", 0.0)
        if composite_g is not None and composite_g >= self.thresholds["imu_impact_g"]:
            alerts.append(Alert(
                AlertLevel.CRITICAL, "imu",
                f"Impact detected: {composite_g}g (threshold: {self.thresholds['imu_impact_g']}g)",
                composite_g
            ))

        # GPS fix check
        gps = telemetry.get("gps", {})
        if gps.get("fix") is False and gps.get("status") != "SIMULATED":
            alerts.append(Alert(
                AlertLevel.WARNING, "gps",
                "GPS has no satellite fix",
                0.0
            ))

        self._active_alerts = alerts
        return alerts

    def get_recommended_actions(self, alerts: List[Alert]) -> Dict[str, Any]:
        """
        Returns recommended actuator actions based on alert severity.
        The caller decides whether to actually execute these.
        """
        if not alerts:
            return {
                "traffic_light": "GREEN",
                "buzzer": False,
                "servo_action": None,
            }

        max_level = AlertLevel.NORMAL
        for alert in alerts:
            if alert.level == AlertLevel.CRITICAL:
                max_level = AlertLevel.CRITICAL
                break
            elif alert.level == AlertLevel.WARNING:
                max_level = AlertLevel.WARNING

        if max_level == AlertLevel.CRITICAL:
            return {
                "traffic_light": "RED",
                "buzzer": True,
                "servo_action": "safe_position",
            }
        elif max_level == AlertLevel.WARNING:
            return {
                "traffic_light": "YELLOW",
                "buzzer": False,
                "servo_action": None,
            }
        else:
            return {
                "traffic_light": "GREEN",
                "buzzer": False,
                "servo_action": None,
            }

    @property
    def active_alerts(self) -> List[Dict[str, Any]]:
        return [a.to_dict() for a in self._active_alerts]
