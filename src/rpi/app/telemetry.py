"""
SENTINEL-AI: Unified Telemetry Processor and Formatter.
=======================================================
Processes, validates, formats, and serializes multi-sensor telemetry
snapshots for logging, edge inference, network transmission, and displays.
"""
import json
import time
from typing import Any, Dict, List, Optional, Tuple


class TelemetryFormatter:
    """Utilities for serializing and displaying unified hardware telemetry."""

    @staticmethod
    def to_json(telemetry: Dict[str, Any], indent: Optional[int] = None) -> str:
        """Serializes telemetry dict to JSON string."""
        return json.dumps(telemetry, indent=indent, default=str)

    @staticmethod
    def to_compact_summary(telemetry: Dict[str, Any]) -> str:
        """
        Creates a one-line concise summary string for logging:
        [2026-09-23T12:00:00Z] Temp=24.5C Hum=55% Gas=0.45V/350 (WARM) GPS=FIX(lat=12.97,lon=77.59)
        """
        ts = telemetry.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        temp = telemetry.get("temperature")
        hum = telemetry.get("humidity")
        gas = telemetry.get("gas", {})
        gps = telemetry.get("gps", {})
        imu = telemetry.get("imu", {})

        temp_str = f"{temp:.1f}C" if temp is not None else "N/A"
        hum_str = f"{hum:.1f}%" if hum is not None else "N/A"

        gas_v = gas.get("adc_voltage")
        gas_lvl = gas.get("relative_gas_level")
        is_warm = gas.get("is_warm", False)
        gas_str = f"{gas_v:.2f}V/{gas_lvl:.0f}" if (gas_v is not None and gas_lvl is not None) else "N/A"
        gas_str += " (WARM)" if is_warm else " (WARMING)"

        gps_fix = gps.get("fix", False)
        if gps_fix:
            lat = gps.get("latitude")
            lon = gps.get("longitude")
            gps_str = f"FIX(lat={lat:.4f},lon={lon:.4f})" if lat and lon else "FIX"
        else:
            gps_str = f"NO_FIX({gps.get('fix_status', 'SEARCHING')})"

        comp_g = imu.get("composite_g", 0.0)
        impact = " [IMPACT!]" if imu.get("impact_detected") else ""

        return (
            f"[{ts}] Temp={temp_str} Hum={hum_str} Gas={gas_str} "
            f"GPS={gps_str} Accel={comp_g:.2f}g{impact}"
        )

    @staticmethod
    def format_lcd_lines(
        telemetry: Dict[str, Any],
        alerts: Optional[List[Dict[str, Any]]] = None,
        ai_decision: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, str]:
        """
        Formats two 16-character lines tailored for 16x2 HD44780 LCD display.
        Prioritizes critical AI emergency decisions & alerts, then standard telemetry.
        """
        # 1. Critical AI Emergency Event (Accident, Fire, etc.)
        if ai_decision and ai_decision.get("severity") in ("CRITICAL", "HIGH"):
            ev = str(ai_decision.get("event", "EMERGENCY"))[:12]
            conf = int(ai_decision.get("confidence", 0.9) * 100)
            temp = telemetry.get("temperature", 0)
            gas = telemetry.get("gas", {}).get("relative_gas_level", 0)
            line1 = f"! {ev} {conf}%".ljust(16)[:16]
            line2 = f"T:{temp:.0f}C Gas:{gas:.0f}".ljust(16)[:16]
            return line1, line2

        # 2. Standard Alert Override
        if alerts and len(alerts) > 0:
            top_alert = alerts[0]
            src = str(top_alert.get("source", "ALERT")).upper()[:12]
            msg = str(top_alert.get("message", "Triggered"))[:16]
            return f"! {src}".ljust(16)[:16], msg.ljust(16)[:16]

        # 3. Nominal flow with AI Event Tag
        temp = telemetry.get("temperature")
        hum = telemetry.get("humidity")
        gas = telemetry.get("gas", {})

        t_val = f"{temp:.0f}C" if temp is not None else "--C"
        h_val = f"{hum:.0f}%" if hum is not None else "--%"
        gas_lvl = gas.get("relative_gas_level", 0)
        line1 = f"T:{t_val} H:{h_val} G:{gas_lvl:.0f}".ljust(16)[:16]

        if ai_decision:
            ev = str(ai_decision.get("event", "NORMAL"))[:9]
            conf = int(ai_decision.get("confidence", 0.9) * 100)
            line2 = f"AI:{ev} {conf}%".ljust(16)[:16]
        else:
            gps_fix = telemetry.get("gps", {}).get("fix", False)
            gps_tag = "OK" if gps_fix else "NO"
            line2 = f"GPS:{gps_tag} SYS:ONLINE".ljust(16)[:16]

        return line1, line2

    @staticmethod
    def format_cli_table(telemetry: Dict[str, Any]) -> str:
        """Formats telemetry as an aligned human-readable CLI table."""
        ts = telemetry.get("timestamp", "N/A")
        temp = telemetry.get("temperature")
        hum = telemetry.get("humidity")
        imu = telemetry.get("imu", {})
        accel = imu.get("accelerometer", {})
        gyro = imu.get("gyroscope", {})
        mag = imu.get("magnetometer", {})
        gas = telemetry.get("gas", {})
        gps = telemetry.get("gps", {})
        audio = telemetry.get("audio", {})
        act = telemetry.get("actuators", {})
        sys_status = telemetry.get("system", {})

        temp_display = f"{temp:.1f} C" if temp is not None else "N/A"
        hum_display = f"{hum:.1f} %" if hum is not None else "N/A"
        gas_adc = str(gas.get("raw_adc", "N/A"))
        gas_v = gas.get("adc_voltage")
        gas_volt_str = f"{gas_v:.3f} V" if gas_v is not None else "N/A"
        gas_rel = str(gas.get("relative_gas_level", "N/A"))
        gas_warm = str(gas.get("is_warm"))

        lines = [
            "+--------------------------------------------------------------+",
            "|               SENTINEL-AI EDGE TELEMETRY SNAPSHOT            |",
            f"| Timestamp: {ts:<49} |",
            "+--------------------------------------------------------------+",
            f"| Environment:  Temp: {temp_display:<10} Humidity: {hum_display:<15}     |",
            f"| Gas (MQ-2):   ADC: {gas_adc:<8} Volt: {gas_volt_str:<8} Rel: {gas_rel:<6} (Warm: {gas_warm}) |",
            f"| IMU (GY-87):  Composite: {imu.get('composite_g', 0.0):.2f}g | Press: {imu.get('pressure', 'N/A')} hPa | Alt: {imu.get('altitude', 'N/A')} m |",
            f"|   Accel (g):  X={accel.get('x_g', 0.0):+.2f}  Y={accel.get('y_g', 0.0):+.2f}  Z={accel.get('z_g', 0.0):+.2f}                    |",
            f"|   Gyro (dps): X={gyro.get('x_dps', 0.0):+.1f}  Y={gyro.get('y_dps', 0.0):+.1f}  Z={gyro.get('z_dps', 0.0):+.1f}                 |",
            f"|   Heading:    {mag.get('heading_deg', 'N/A')} deg                                            |",
            f"| GPS (NEO-6M): Fix: {str(gps.get('fix')):<5} Sats: {str(gps.get('satellites', 0)):<4} Status: {str(gps.get('fix_status', 'N/A')):<12}            |",
            f"|   Location:   Lat={gps.get('latitude', 'N/A')}  Lon={gps.get('longitude', 'N/A')}  Alt={gps.get('altitude', 'N/A')}m      |",
            f"| Audio (I2S):  RMS: {str(audio.get('rms', 'N/A')):<8} dB: {str(audio.get('level_db', 'N/A')):<8} Status: {str(audio.get('status', 'N/A')):<10}  |",
            f"| Actuators:    LEDs: R={int(act.get('red_led', False))} Y={int(act.get('yellow_led', False))} G={int(act.get('green_led', False))} Buzzer={int(act.get('buzzer', False))} Servo={act.get('servo_angle', 90)} deg    |",
            f"| System:       LCD: {str(sys_status.get('lcd', 'N/A')):<10} I2C: {str(sys_status.get('i2c', 'N/A')):<10} Cam: {str(sys_status.get('camera', 'N/A')):<8}       |",
            "+--------------------------------------------------------------+",
        ]
        return "\n".join(lines)
