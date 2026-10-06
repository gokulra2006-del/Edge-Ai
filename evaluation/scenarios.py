"""Incident scenario definitions, deterministic generator, loaders, and fault injectors."""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

DataTag = Literal["SYNTHETIC", "REPLAYED_REAL", "REAL_HARDWARE"]
EventClass = Literal["NORMAL", "ACCIDENT", "FIRE", "AMBULANCE"]
FaultType = Literal[
    "none",
    "camera_dropout",
    "audio_silence",
    "audio_clipping",
    "sensor_stuck",
    "sensor_noise",
    "delayed_streams",
    "network_outage",
    "conflicting_sensors",
]


@dataclass
class EnvironmentalConditions:
    time_of_day: str = "day"                     # "day", "night"
    weather: str = "clear"                       # "clear", "rain", "fog"
    camera_angle: str = "overhead"               # "overhead", "street_level", "oblique"
    traffic_density: str = "medium"              # "low", "medium", "high"
    microphone_placement: str = "pole_mounted"   # "pole_mounted", "curbside", "enclosed"
    road_surface: str = "asphalt"                # "asphalt", "wet_concrete", "gravel"
    acoustic_zone: str = "quiet_suburb"          # "quiet_suburb", "noisy_intersection", "commercial"
    hardware_node: str = "rpi4_node1"            # "rpi4_node1", "jetson_node2", "edge_server"

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]] = None) -> "EnvironmentalConditions":
        if not data:
            return cls()
        fields = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in fields})


@dataclass
class SensorReading:
    timestamp: float
    temperature: float
    smoke_ppm: float
    imu_accel_z: float = 1.0
    air_quality_index: float = 45.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AudioReading:
    timestamp: float
    decibels: float
    mel_top_class: str
    mel_confidence: float
    siren_detected: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VisionReading:
    timestamp: float
    detected_classes: List[str]
    confidences: Dict[str, float]
    fps: float = 15.0
    bounding_boxes: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScenarioStep:
    step_idx: int
    timestamp_offset: float
    sensors: SensorReading
    audio: AudioReading
    vision: VisionReading
    ground_truth: EventClass
    network_online: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Scenario:
    scenario_id: str
    version: str
    name: str
    zone: str
    data_tag: DataTag
    duration_seconds: float
    event_onset_time: Optional[float]
    ground_truth_event: EventClass
    steps: List[ScenarioStep]
    fault_type: FaultType = "none"
    seed: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    conditions: EnvironmentalConditions = field(default_factory=EnvironmentalConditions)

    def compute_hash(self) -> str:
        serialized = json.dumps(
            {
                "id": self.scenario_id,
                "version": self.version,
                "zone": self.zone,
                "duration": self.duration_seconds,
                "onset": self.event_onset_time,
                "event": self.ground_truth_event,
                "fault": self.fault_type,
                "tag": self.data_tag,
                "conditions": self.conditions.to_dict(),
                "steps": [
                    {
                        "idx": s.step_idx,
                        "t": s.timestamp_offset,
                        "gt": s.ground_truth,
                        "net": s.network_online,
                        "s": asdict(s.sensors),
                        "a": asdict(s.audio),
                        "v": asdict(s.vision),
                    }
                    for s in self.steps
                ],
            },
            sort_keys=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Scenario":
        steps_raw = data.get("steps", [])
        steps: List[ScenarioStep] = []
        for s in steps_raw:
            sensors = SensorReading(**s["sensors"])
            audio = AudioReading(**s["audio"])
            vision = VisionReading(**s["vision"])
            steps.append(
                ScenarioStep(
                    step_idx=s["step_idx"],
                    timestamp_offset=s["timestamp_offset"],
                    sensors=sensors,
                    audio=audio,
                    vision=vision,
                    ground_truth=s["ground_truth"],
                    network_online=s.get("network_online", True),
                    metadata=s.get("metadata", {}),
                )
            )
        data_copy = dict(data)
        data_copy["steps"] = steps
        if "conditions" in data_copy and isinstance(data_copy["conditions"], dict):
            data_copy["conditions"] = EnvironmentalConditions.from_dict(data_copy["conditions"])
        elif "conditions" not in data_copy:
            data_copy["conditions"] = EnvironmentalConditions()
        return cls(**data_copy)


class ScenarioGenerator:
    """Generates synthetic, deterministic, versioned incident evaluation scenarios."""

    ZONES = ["ZONE_A_INTERSECTION", "ZONE_B_INTERSECTION", "ZONE_C_CORRIDOR"]
    CLASSES: List[EventClass] = ["NORMAL", "ACCIDENT", "FIRE", "AMBULANCE"]

    def __init__(self, seed: int = 42, step_duration: float = 0.5):
        self.seed = seed
        self.step_duration = step_duration

    def generate_suite(
        self,
        count_per_class: int = 5,
        duration_seconds: float = 10.0,
        data_tag: DataTag = "SYNTHETIC",
    ) -> List[Scenario]:
        rng = random.Random(self.seed)
        scenarios: List[Scenario] = []

        scenario_idx = 0
        for ev_class in self.CLASSES:
            for i in range(count_per_class):
                scenario_idx += 1
                zone = rng.choice(self.ZONES)
                sc = self._generate_single_scenario(
                    scenario_id=f"SCENARIO-{scenario_idx:03d}-{ev_class}",
                    name=f"Synthetic {ev_class} Simulation #{i+1}",
                    zone=zone,
                    event_class=ev_class,
                    duration_seconds=duration_seconds,
                    rng=rng,
                    data_tag=data_tag,
                )
                scenarios.append(sc)

        return scenarios

    def _generate_single_scenario(
        self,
        scenario_id: str,
        name: str,
        zone: str,
        event_class: EventClass,
        duration_seconds: float,
        rng: random.Random,
        data_tag: DataTag,
        conditions: Optional[EnvironmentalConditions] = None,
    ) -> Scenario:
        conditions = conditions or EnvironmentalConditions()
        num_steps = int(duration_seconds / self.step_duration)
        onset_step = 0 if event_class == "NORMAL" else rng.randint(3, max(4, num_steps // 2))
        event_onset_time = None if event_class == "NORMAL" else onset_step * self.step_duration

        steps: List[ScenarioStep] = []
        for step in range(num_steps):
            t = step * self.step_duration
            is_active = (event_class != "NORMAL") and (step >= onset_step)
            current_gt: EventClass = event_class if is_active else "NORMAL"

            # 1. Telemetry
            if current_gt == "FIRE":
                temp = 25.0 + rng.uniform(40.0, 75.0)
                smoke = 20.0 + rng.uniform(150.0, 450.0)
                imu_z = 1.0 + rng.uniform(-0.1, 0.1)
            elif current_gt == "ACCIDENT":
                temp = 24.0 + rng.uniform(0.0, 4.0)
                smoke = 15.0 + rng.uniform(0.0, 20.0)
                imu_z = 3.5 + rng.uniform(0.5, 3.0) if step == onset_step else 1.0
            else:
                temp = 22.0 + rng.uniform(-2.0, 3.0)
                smoke = 10.0 + rng.uniform(0.0, 15.0)
                imu_z = 1.0 + rng.uniform(-0.05, 0.05)

            sensors = SensorReading(
                timestamp=t,
                temperature=round(temp, 2),
                smoke_ppm=round(smoke, 2),
                imu_accel_z=round(imu_z, 2),
                air_quality_index=round(min(500.0, smoke * 0.8), 1),
            )

            # 2. Acoustic
            if current_gt == "AMBULANCE":
                db = rng.uniform(85.0, 98.0)
                mel_class = "siren"
                mel_conf = rng.uniform(0.85, 0.98)
                siren = True
            elif current_gt == "ACCIDENT":
                db = rng.uniform(88.0, 102.0) if step in (onset_step, onset_step + 1) else rng.uniform(60.0, 75.0)
                mel_class = "car_crash" if step in (onset_step, onset_step + 1) else "traffic"
                mel_conf = rng.uniform(0.80, 0.95) if mel_class == "car_crash" else rng.uniform(0.40, 0.70)
                siren = False
            elif current_gt == "FIRE":
                db = rng.uniform(65.0, 78.0)
                mel_class = "fire_alarm"
                mel_conf = rng.uniform(0.70, 0.92)
                siren = False
            else:
                db = rng.uniform(50.0, 68.0)
                mel_class = "ambient_traffic"
                mel_conf = rng.uniform(0.50, 0.75)
                siren = False

            # 3. Vision
            if current_gt == "FIRE":
                det = ["fire", "smoke"]
                confs = {"fire": round(rng.uniform(0.75, 0.96), 3), "smoke": round(rng.uniform(0.70, 0.92), 3)}
            elif current_gt == "ACCIDENT":
                det = ["damaged_vehicle", "debris"]
                confs = {"damaged_vehicle": round(rng.uniform(0.80, 0.95), 3), "debris": round(rng.uniform(0.65, 0.88), 3)}
            elif current_gt == "AMBULANCE":
                det = ["emergency_vehicle"]
                confs = {"emergency_vehicle": round(rng.uniform(0.78, 0.94), 3)}
            else:
                det = ["car", "pedestrian"]
                confs = {"car": round(rng.uniform(0.60, 0.85), 3), "pedestrian": round(rng.uniform(0.50, 0.80), 3)}

            # Physical condition perturbations
            vis_mult = 1.0
            if conditions.time_of_day == "night":
                vis_mult *= 0.76
            if conditions.weather == "rain":
                vis_mult *= 0.84
            elif conditions.weather == "fog":
                vis_mult *= 0.65
            if conditions.camera_angle == "oblique":
                vis_mult *= 0.88
            elif conditions.camera_angle == "street_level":
                vis_mult *= 0.94

            confs = {k: round(max(0.10, min(0.99, v * vis_mult)), 3) for k, v in confs.items()}
            if conditions.weather == "fog" and current_gt == "NORMAL" and rng.random() < 0.12:
                if "smoke" not in det:
                    det.append("smoke")
                    confs["smoke"] = round(rng.uniform(0.40, 0.60), 3)

            db_offset = 0.0
            mel_mult = 1.0
            if conditions.acoustic_zone == "noisy_intersection":
                db_offset += 12.0
                mel_mult *= 0.82
            elif conditions.acoustic_zone == "commercial":
                db_offset += 6.0
            if conditions.road_surface == "wet_concrete":
                db_offset += 4.0
            elif conditions.road_surface == "gravel":
                db_offset += 5.0
            if conditions.traffic_density == "high":
                db_offset += 5.0
            elif conditions.traffic_density == "low":
                db_offset -= 4.0
            if conditions.microphone_placement == "enclosed":
                db_offset -= 10.0
                mel_mult *= 0.85
            elif conditions.microphone_placement == "curbside":
                db_offset += 3.0

            db = max(35.0, min(120.0, db + db_offset))
            mel_conf = round(max(0.15, min(0.99, mel_conf * mel_mult)), 3)

            audio = AudioReading(
                timestamp=t,
                decibels=round(db, 1),
                mel_top_class=mel_class,
                mel_confidence=round(mel_conf, 3),
                siren_detected=siren,
            )

            vision = VisionReading(
                timestamp=t,
                detected_classes=det,
                confidences=confs,
                fps=15.0,
            )

            steps.append(
                ScenarioStep(
                    step_idx=step,
                    timestamp_offset=t,
                    sensors=sensors,
                    audio=audio,
                    vision=vision,
                    ground_truth=current_gt,
                    network_online=True,
                )
            )

        return Scenario(
            scenario_id=scenario_id,
            version="1.0.0",
            name=name,
            zone=zone,
            data_tag=data_tag,
            duration_seconds=duration_seconds,
            event_onset_time=event_onset_time,
            ground_truth_event=event_class,
            steps=steps,
            fault_type="none",
            seed=self.seed,
            conditions=conditions,
        )

    def generate_robustness_suite(
        self,
        count_per_condition: int = 4,
        duration_seconds: float = 6.0,
    ) -> List[Scenario]:
        """
        Generates a comprehensive evaluation suite stratified across all 8 condition dimensions.
        """
        rng = random.Random(self.seed)
        scenarios: List[Scenario] = []

        dimensions_and_values = [
            ("time_of_day", ["day", "night"]),
            ("weather", ["clear", "rain", "fog"]),
            ("camera_angle", ["overhead", "street_level", "oblique"]),
            ("traffic_density", ["low", "medium", "high"]),
            ("microphone_placement", ["pole_mounted", "curbside", "enclosed"]),
            ("road_surface", ["asphalt", "wet_concrete", "gravel"]),
            ("acoustic_zone", ["quiet_suburb", "noisy_intersection", "commercial"]),
            ("hardware_node", ["rpi4_node1", "jetson_node2", "edge_server"]),
        ]

        real_data_conditions = {
            "time_of_day": {"day"},
            "weather": {"clear"},
            "camera_angle": {"overhead"},
            "traffic_density": {"medium"},
            "microphone_placement": {"pole_mounted"},
            "road_surface": {"asphalt"},
            "acoustic_zone": {"quiet_suburb", "commercial"},
            "hardware_node": {"rpi4_node1"},
        }

        sc_idx = 0
        for dim, values in dimensions_and_values:
            for val in values:
                for ev_class in self.CLASSES:
                    for i in range(max(1, count_per_condition // len(self.CLASSES))):
                        sc_idx += 1
                        cond_kwargs = {dim: val}
                        cond = EnvironmentalConditions(**cond_kwargs)
                        has_real = val in real_data_conditions.get(dim, set())
                        tag: DataTag = "REAL_HARDWARE" if (has_real and dim == "hardware_node") else ("REPLAYED_REAL" if has_real else "SYNTHETIC")
                        zone = rng.choice(self.ZONES)

                        sc = self._generate_single_scenario(
                            scenario_id=f"ROBUST-{sc_idx:04d}-{dim}-{val}-{ev_class}",
                            name=f"Robustness {dim}={val} {ev_class} #{i+1}",
                            zone=zone,
                            event_class=ev_class,
                            duration_seconds=duration_seconds,
                            rng=rng,
                            data_tag=tag,
                            conditions=cond,
                        )
                        scenarios.append(sc)

        return scenarios


class FaultInjector:
    """Applies deterministic, reproducible faults to a Scenario."""

    @staticmethod
    def inject(scenario: Scenario, fault: FaultType, seed: int = 1337) -> Scenario:
        if fault == "none":
            return copy.deepcopy(scenario)

        sc = copy.deepcopy(scenario)
        sc.fault_type = fault
        rng = random.Random(seed)

        for step in sc.steps:
            # 1. Camera dropout: frame drops to empty classes, zero FPS
            if fault == "camera_dropout":
                step.vision.detected_classes = []
                step.vision.confidences = {}
                step.vision.fps = 0.0
                step.vision.metadata["fault"] = "CAMERA_DROPOUT"

            # 2. Audio silence: 0 dB, silent class
            elif fault == "audio_silence":
                step.audio.decibels = 0.0
                step.audio.mel_top_class = "silence"
                step.audio.mel_confidence = 0.0
                step.audio.siren_detected = False
                step.audio.metadata["fault"] = "AUDIO_SILENCE"

            # 3. Audio clipping: extreme distorted decibels, low confidence
            elif fault == "audio_clipping":
                step.audio.decibels = 135.0
                step.audio.mel_top_class = "clipping_distortion"
                step.audio.mel_confidence = 0.15
                step.audio.metadata["fault"] = "AUDIO_CLIPPING"

            # 4. Sensor stuck: temperature and smoke frozen at zero
            elif fault == "sensor_stuck":
                step.sensors.temperature = 0.0
                step.sensors.smoke_ppm = 0.0
                step.sensors.imu_accel_z = 0.0
                step.sensors.metadata["fault"] = "SENSOR_STUCK"

            # 5. Sensor noise: extreme Gaussian noise
            elif fault == "sensor_noise":
                step.sensors.temperature += rng.gauss(0, 50.0)
                step.sensors.smoke_ppm = max(0.0, step.sensors.smoke_ppm + rng.gauss(0, 200.0))
                step.sensors.metadata["fault"] = "SENSOR_NOISE"

            # 6. Delayed streams: vision timestamp lagged by 5.0 seconds
            elif fault == "delayed_streams":
                step.vision.timestamp = max(0.0, step.vision.timestamp - 5.0)
                step.vision.metadata["fault"] = "STREAM_DELAY_5S"

            # 7. Network outage: network_online flag set to False
            elif fault == "network_outage":
                step.network_online = False
                step.metadata["fault"] = "NETWORK_OUTAGE"

            # 8. Conflicting sensors: vision claims fire while audio/sensors report calm ambient
            elif fault == "conflicting_sensors":
                step.vision.detected_classes = ["fire"]
                step.vision.confidences = {"fire": 0.95}
                step.sensors.smoke_ppm = 5.0
                step.sensors.temperature = 18.0
                step.audio.mel_top_class = "silence"
                step.metadata["fault"] = "CONFLICTING_SENSORS"

        return sc
