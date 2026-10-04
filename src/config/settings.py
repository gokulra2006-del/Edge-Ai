"""
Configuration settings for the Edge-AI Urban Emergency Network.
Raspberry Pi 4 target specifications and sensor fusion weights.
"""
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class SystemConfig:
    # Node identity
    node_id: str = "NODE_B"
    zone_name: str = "INTERSECTION_4_MAIN_ROAD"
    
    # Fusion Weights
    # Accident: Acoustic Crash (0.45) + IMU Impact (0.35) + Camera Vehicle (0.20)
    w_audio_crash: float = 0.45
    w_imu_impact: float = 0.35
    w_vision_vehicle: float = 0.20
    
    # Emergency Vehicle: Acoustic Siren (0.60) + Camera Congestion/Vehicle (0.40)
    w_audio_siren: float = 0.60
    w_vision_siren: float = 0.40
    
    # Fire/Hazard: Camera Fire/Smoke (0.50) + Smoke/Temp Sensors (0.50)
    w_vision_fire: float = 0.50
    w_env_fire: float = 0.50
    
    # Thresholds
    min_event_confidence: float = 0.65
    high_temp_threshold_c: float = 50.0
    critical_smoke_threshold_ppm: float = 120.0
    impact_g_threshold: float = 2.5
    
    # Database
    db_path: str = str(DATA_DIR / "emergency_events.db")
    
    # Dashboard API
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8080


CONFIG = SystemConfig()
