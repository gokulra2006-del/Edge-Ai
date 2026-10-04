"""
Data models and typed structures for the Edge-AI emergency response pipeline.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any


@dataclass
class AudioPrediction:
    class_name: str          # e.g., "crash", "ambulance", "firetruck", "police", "horn", "traffic"
    confidence: float        # 0.0 to 1.0
    features: Dict[str, float] = field(default_factory=dict)


@dataclass
class VisionPrediction:
    detected_classes: List[str]   # e.g., ["vehicle", "fire", "smoke", "pothole"]
    primary_class: str            # dominant class
    confidence: float             # 0.0 to 1.0
    bounding_boxes: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class IMUReading:
    impact_detected: bool
    g_force: float               # measured g-force (e.g. 1.0 = baseline 1g, >2.5g = collision)
    confidence: float            # 0.0 to 1.0
    axes: Dict[str, float] = field(default_factory=lambda: {"ax": 0.0, "ay": 0.0, "az": 1.0})


@dataclass
class EnvironmentReading:
    temperature_c: float         # Ambient temp in Celsius
    smoke_ppm: float             # Smoke concentration in PPM


@dataclass
class SensorPacket:
    timestamp: str
    node_id: str
    audio_prediction: AudioPrediction
    vision_prediction: VisionPrediction
    imu_reading: IMUReading
    environment: EnvironmentReading
    raw_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FusedEvent:
    timestamp: str
    event_type: str              # "ACCIDENT", "EMERGENCY_VEHICLE", "FIRE_HAZARD", "ROAD_HAZARD", "NORMAL"
    confidence: float            # Combined multi-modal confidence
    contributing_modalities: List[str]  # ["audio", "vision", "imu", "environment"]
    is_verified: bool            # True if multiple independent sensors agree
    raw_packet: SensorPacket


@dataclass
class SeverityAssessment:
    level: str                   # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    score: float                 # 0.0 to 1.0
    rationale: str               # Human-readable justification


@dataclass
class LocationEstimate:
    primary_node: str            # e.g., "NODE_B"
    probable_zone: str           # e.g., "ZONE_B_NORTH_INTERSECTION"
    zone_confidence: float       # Multi-node arrival/RSSI estimate (e.g. 0.94)
    all_node_probabilities: Dict[str, float] = field(default_factory=dict)


@dataclass
class ResponseAction:
    traffic_signal_state: str    # "NORMAL_CYCLE", "EMERGENCY_GREEN_CORRIDOR", "RESTRICT_AFFECTED_LANE", "ALL_RED_STOP"
    green_corridor_active: bool
    lane_restricted: Optional[str]
    alert_type: str              # "NONE", "DISPATCH_AMBULANCE", "DISPATCH_FIRE_ENGINE", "HAZARD_ADVISORY"
    warning_leds_active: bool
    buzzer_active: bool
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
