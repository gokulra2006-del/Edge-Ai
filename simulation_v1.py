"""
FIRST WORKING SOFTWARE VERSION: Edge-AI Emergency Detection Network Simulation.
Raspberry Pi 4 Architecture - Software Simulation Mode (NO GPIO / NO PHYSICAL HARDWARE).

Implements:
1. Simulated Audio Input
2. Simulated Vision Input
3. Simulated MPU6050 Impact Input
4. Simulated Temperature
5. Simulated Smoke
6. Sensor Fusion
7. Event Classification
8. Severity Classification
9. Event Logging (SQLite + Console)
"""
import os
import sys
import sqlite3
import json
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "simulation_v1_events.db"


# =============================================================================
# DATA STRUCTURES
# =============================================================================
@dataclass
class SimulatedSensors:
    audio_class: str            # "crash", "siren", "horn", "traffic"
    audio_confidence: float     # 0.0 to 1.0
    vision_class: str           # "vehicle", "fire", "smoke", "none"
    vision_confidence: float    # 0.0 to 1.0
    imu_impact: bool            # True / False (MPU6050 impact detection)
    imu_g_force: float          # Accelerometer g-force (e.g. 1.0 = normal, >2.5 = crash)
    temperature_c: float        # Ambient temperature in Celsius
    smoke_ppm: float            # Smoke concentration in PPM


@dataclass
class ResponseState:
    traffic_signal: str         # "RED", "GREEN", "GREEN (CORRIDOR)"
    barrier_gate: str           # "CLOSED", "OPEN"
    buzzer_alarm: str           # "ON", "OFF"
    alert_dispatch: str         # Dispatch message


@dataclass
class EmergencyEventResult:
    event: str                  # "ACCIDENT", "FIRE", "EMERGENCY_VEHICLE", "NORMAL"
    confidence: float           # 0.0 to 1.0
    severity: str               # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    sensors: SimulatedSensors
    response: ResponseState
    verified: bool
    modalities: List[str]


# =============================================================================
# 6. SENSOR FUSION & 7. EVENT CLASSIFICATION ENGINE
# =============================================================================
class EdgeSensorFusion:
    """
    Multi-sensor fusion logic correlating Audio + Vision + MPU6050 IMU + Env.
    Filters out single-sensor anomalies (e.g. horn alone, parked vehicle alone).
    """
    def __init__(self):
        # Weights for accident fusion
        self.w_aud = 0.45
        self.w_imu = 0.35
        self.w_vis = 0.20

    def fuse_and_classify(self, s: SimulatedSensors) -> EmergencyEventResult:
        modalities = []
        
        # -------------------------------------------------------------
        # 1. ACCIDENT RULE:
        # Crash sound + IMU impact + Vehicle visually present
        # -------------------------------------------------------------
        if s.audio_class.lower() == "crash" and s.audio_confidence >= 0.60:
            modalities.append("AUDIO")
            if s.imu_impact or s.imu_g_force >= 2.5:
                modalities.append("IMU")
            if s.vision_class.lower() in ["vehicle", "car", "truck", "bus"] and s.vision_confidence >= 0.50:
                modalities.append("VISION")

            # Weighted confidence calculation
            conf_aud = s.audio_confidence
            conf_imu = 1.0 if ("IMU" in modalities) else 0.10
            conf_vis = s.vision_confidence if ("VISION" in modalities) else 0.20
            fused_conf = (self.w_aud * conf_aud) + (self.w_imu * conf_imu) + (self.w_vis * conf_vis)

            # Verified if at least 2 modalities corroborate
            is_verified = len(modalities) >= 2

            if is_verified and "IMU" in modalities:
                return self._build_result(
                    event="ACCIDENT",
                    confidence=fused_conf,
                    severity="CRITICAL",
                    sensors=s,
                    traffic="RED",
                    barrier="CLOSED",
                    buzzer="ON",
                    alert="DISPATCH AMBULANCE & POLICE (CRITICAL COLLISION)",
                    verified=True,
                    modalities=modalities
                )

        # -------------------------------------------------------------
        # 2. FIRE HAZARD RULE:
        # Fire/Smoke vision + High smoke ppm + High temperature
        # -------------------------------------------------------------
        is_visual_fire = s.vision_class.lower() in ["fire", "smoke"] and s.vision_confidence >= 0.65
        is_env_fire = s.temperature_c >= 50.0 or s.smoke_ppm >= 100.0

        if is_visual_fire or is_env_fire:
            if is_visual_fire:
                modalities.append("VISION")
            if is_env_fire:
                modalities.append("ENVIRONMENT")

            conf_vis = s.vision_confidence if is_visual_fire else 0.40
            conf_env = min(1.0, (s.smoke_ppm / 200.0) * 0.5 + (s.temperature_c / 80.0) * 0.5)
            fused_conf = (0.50 * conf_vis) + (0.50 * conf_env)

            severity = "CRITICAL" if (s.smoke_ppm >= 150.0 and s.temperature_c >= 55.0) else "HIGH"

            return self._build_result(
                event="FIRE",
                confidence=fused_conf,
                severity=severity,
                sensors=s,
                traffic="RED",
                barrier="CLOSED",
                buzzer="ON",
                alert="DISPATCH FIRE SERVICES & ACTIVATE VENTILATION",
                verified=len(modalities) >= 2,
                modalities=modalities
            )

        # -------------------------------------------------------------
        # 3. EMERGENCY VEHICLE RULE:
        # Siren detected + Vehicle visible
        # -------------------------------------------------------------
        if s.audio_class.lower() in ["siren", "ambulance", "firetruck", "police"] and s.audio_confidence >= 0.70:
            modalities.append("AUDIO")
            has_vehicle = s.vision_class.lower() in ["vehicle", "car", "truck", "bus"]
            if has_vehicle:
                modalities.append("VISION")

            fused_conf = (0.60 * s.audio_confidence) + (0.40 * (s.vision_confidence if has_vehicle else 0.50))

            return self._build_result(
                event="EMERGENCY_VEHICLE",
                confidence=fused_conf,
                severity="HIGH",
                sensors=s,
                traffic="GREEN (CORRIDOR)",
                barrier="OPEN",
                buzzer="OFF",
                alert="DYNAMIC EMERGENCY GREEN CORRIDOR PRIORITY ACTIVATED",
                verified=True,
                modalities=modalities
            )

        # -------------------------------------------------------------
        # 4. FALSE ALARM REJECTION (e.g. Horn alone, no impact, normal visual):
        # -------------------------------------------------------------
        if s.audio_class.lower() == "horn":
            modalities.append("AUDIO (TRANSIENT HORN)")
            # Suppressed: Horn alone without impact or crash visuals is deemed normal traffic noise
            return self._build_result(
                event="NORMAL",
                confidence=0.85,
                severity="LOW",
                sensors=s,
                traffic="GREEN",
                barrier="OPEN",
                buzzer="OFF",
                alert="NO ACTION (HORN NOISE FILTERED BY FUSION)",
                verified=True,
                modalities=modalities
            )

        # -------------------------------------------------------------
        # 5. NORMAL TRAFFIC (BASELINE)
        # -------------------------------------------------------------
        modalities.append("BASELINE")
        return self._build_result(
            event="NORMAL",
            confidence=0.90,
            severity="LOW",
            sensors=s,
            traffic="GREEN",
            barrier="OPEN",
            buzzer="OFF",
            alert="NORMAL CYCLIC TRAFFIC FLOW",
            verified=True,
            modalities=modalities
        )

    def _build_result(
        self, event, confidence, severity, sensors, traffic, barrier, buzzer, alert, verified, modalities
    ) -> EmergencyEventResult:
        return EmergencyEventResult(
            event=event,
            confidence=round(confidence, 4),
            severity=severity,
            sensors=sensors,
            response=ResponseState(
                traffic_signal=traffic,
                barrier_gate=barrier,
                buzzer_alarm=buzzer,
                alert_dispatch=alert
            ),
            verified=verified,
            modalities=modalities
        )


# =============================================================================
# 9. EVENT LOGGING (SQLITE PERSISTENCE)
# =============================================================================
class SimulationLogger:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS event_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    severity TEXT NOT NULL,
                    audio_info TEXT NOT NULL,
                    vision_info TEXT NOT NULL,
                    impact_info TEXT NOT NULL,
                    temperature REAL NOT NULL,
                    smoke_ppm REAL NOT NULL,
                    traffic_signal TEXT NOT NULL,
                    barrier TEXT NOT NULL,
                    buzzer TEXT NOT NULL
                )
            """)
            conn.commit()

    def log(self, res: EmergencyEventResult) -> int:
        smoke_str = "HIGH" if res.sensors.smoke_ppm >= 100.0 else "LOW"
        impact_str = "DETECTED" if res.sensors.imu_impact else "NONE"
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO event_log (
                    timestamp, event, confidence, severity, audio_info,
                    vision_info, impact_info, temperature, smoke_ppm,
                    traffic_signal, barrier, buzzer
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                res.event,
                res.confidence,
                res.severity,
                f"{res.sensors.audio_class.upper()} {int(res.sensors.audio_confidence * 100)}%",
                f"{res.sensors.vision_class.upper()} {int(res.sensors.vision_confidence * 100)}%",
                impact_str,
                res.sensors.temperature_c,
                res.sensors.smoke_ppm,
                res.response.traffic_signal,
                res.response.barrier_gate,
                res.response.buzzer_alarm
            ))
            conn.commit()
            return cursor.lastrowid


# =============================================================================
# FORMATTED CONSOLE PRINTER (MATCHES EXACT PROMPT FORMAT)
# =============================================================================
def print_scenario_result(scenario_title: str, res: EmergencyEventResult, log_id: int):
    smoke_label = "HIGH" if res.sensors.smoke_ppm >= 100.0 else "LOW"
    impact_label = "DETECTED" if res.sensors.imu_impact else "NONE"

    print("=" * 65)
    print(f"  {scenario_title.upper()}")
    print("=" * 65)
    print(f"EVENT: {res.event}")
    print(f"CONFIDENCE: {int(res.confidence * 100)}%")
    print(f"SEVERITY: {res.severity}\n")

    print(f"AUDIO: {res.sensors.audio_class.upper()} {int(res.sensors.audio_confidence * 100)}%")
    print(f"VISION: {res.sensors.vision_class.upper()} {int(res.sensors.vision_confidence * 100)}%")
    print(f"IMPACT: {impact_label}")
    print(f"TEMPERATURE: {res.sensors.temperature_c:.1f} C")
    print(f"SMOKE: {smoke_label} ({res.sensors.smoke_ppm:.0f} ppm)\n")

    print("RESPONSE:")
    print(f"TRAFFIC = {res.response.traffic_signal}")
    print(f"BARRIER = {res.response.barrier_gate}")
    print(f"BUZZER = {res.response.buzzer_alarm}")
    print(f"ALERT = {res.response.alert_dispatch}")
    print(f"[LOGGED]: SQLite Event #{log_id}\n")


# =============================================================================
# MAIN PREDEFINED TEST SCENARIOS
# =============================================================================
def run_all_scenarios():
    fusion_engine = EdgeSensorFusion()
    logger = SimulationLogger()

    # -------------------------------------------------------------------------
    # SCENARIO 1: NORMAL TRAFFIC
    # -------------------------------------------------------------------------
    s1 = SimulatedSensors(
        audio_class="traffic",
        audio_confidence=0.90,
        vision_class="vehicle",
        vision_confidence=0.85,
        imu_impact=False,
        imu_g_force=1.0,
        temperature_c=28.0,
        smoke_ppm=10.0
    )
    r1 = fusion_engine.fuse_and_classify(s1)
    id1 = logger.log(r1)
    print_scenario_result("SCENARIO 1: Normal Traffic", r1, id1)

    # -------------------------------------------------------------------------
    # SCENARIO 2: ACCIDENT (Crash audio + Vehicle detected + Impact detected)
    # -------------------------------------------------------------------------
    s2 = SimulatedSensors(
        audio_class="crash",
        audio_confidence=0.87,
        vision_class="vehicle",
        vision_confidence=0.91,
        imu_impact=True,
        imu_g_force=4.2,
        temperature_c=32.5,
        smoke_ppm=25.0
    )
    r2 = fusion_engine.fuse_and_classify(s2)
    id2 = logger.log(r2)
    print_scenario_result("SCENARIO 2: Accident", r2, id2)

    # -------------------------------------------------------------------------
    # SCENARIO 3: FIRE (Fire/smoke detected + High smoke + Elevated temp)
    # -------------------------------------------------------------------------
    s3 = SimulatedSensors(
        audio_class="traffic",
        audio_confidence=0.50,
        vision_class="fire",
        vision_confidence=0.89,
        imu_impact=False,
        imu_g_force=1.0,
        temperature_c=68.5,
        smoke_ppm=240.0
    )
    r3 = fusion_engine.fuse_and_classify(s3)
    id3 = logger.log(r3)
    print_scenario_result("SCENARIO 3: Fire Hazard", r3, id3)

    # -------------------------------------------------------------------------
    # SCENARIO 4: EMERGENCY VEHICLE (Siren detected + Vehicle detected)
    # -------------------------------------------------------------------------
    s4 = SimulatedSensors(
        audio_class="siren",
        audio_confidence=0.95,
        vision_class="vehicle",
        vision_confidence=0.88,
        imu_impact=False,
        imu_g_force=1.0,
        temperature_c=29.0,
        smoke_ppm=15.0
    )
    r4 = fusion_engine.fuse_and_classify(s4)
    id4 = logger.log(r4)
    print_scenario_result("SCENARIO 4: Emergency Vehicle (Green Corridor)", r4, id4)

    # -------------------------------------------------------------------------
    # SCENARIO 5: FALSE ALARM (Horn detected + No impact + No accident visuals)
    # -------------------------------------------------------------------------
    s5 = SimulatedSensors(
        audio_class="horn",
        audio_confidence=0.92,
        vision_class="vehicle",
        vision_confidence=0.80,
        imu_impact=False,
        imu_g_force=1.0,
        temperature_c=29.5,
        smoke_ppm=12.0
    )
    r5 = fusion_engine.fuse_and_classify(s5)
    id5 = logger.log(r5)
    print_scenario_result("SCENARIO 5: False Alarm (Horn Filtered)", r5, id5)


if __name__ == "__main__":
    run_all_scenarios()
