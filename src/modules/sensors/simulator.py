"""
Module 1: Simulated Sensor Hub.
Provides realistic software simulated readings for development and validation
without requiring physical Raspberry Pi GPIO or connected sensors.
"""
from datetime import datetime
from typing import Dict, Any, Optional
from src.core.data_models import (
    AudioPrediction,
    VisionPrediction,
    IMUReading,
    EnvironmentReading,
    SensorPacket
)
from src.config.settings import CONFIG


class SimulatedSensorHub:
    def __init__(self, node_id: Optional[str] = None):
        self.node_id = node_id or CONFIG.node_id

    def generate_packet(
        self,
        audio_class: str = "traffic",
        audio_conf: float = 0.85,
        vision_class: str = "vehicle",
        vision_conf: float = 0.90,
        imu_impact: bool = False,
        imu_g: float = 1.0,
        temp_c: float = 30.0,
        smoke_ppm: float = 15.0
    ) -> SensorPacket:
        """Generates a custom sensor packet matching exact parameter inputs."""
        return SensorPacket(
            timestamp=datetime.now().isoformat(),
            node_id=self.node_id,
            audio_prediction=AudioPrediction(
                class_name=audio_class,
                confidence=audio_conf
            ),
            vision_prediction=VisionPrediction(
                detected_classes=[vision_class],
                primary_class=vision_class,
                confidence=vision_conf
            ),
            imu_reading=IMUReading(
                impact_detected=imu_impact,
                g_force=imu_g,
                confidence=1.0 if imu_impact else 0.95
            ),
            environment=EnvironmentReading(
                temperature_c=temp_c,
                smoke_ppm=smoke_ppm
            )
        )

    # Preset Scenarios
    def scenario_accident(self) -> SensorPacket:
        """User example: Crash sound + vehicle vision + IMU impact + moderate smoke/temp."""
        return self.generate_packet(
            audio_class="crash",
            audio_conf=0.87,
            vision_class="vehicle",
            vision_conf=0.91,
            imu_impact=True,
            imu_g=4.2,
            temp_c=32.5,
            smoke_ppm=120.0
        )

    def scenario_emergency_siren(self) -> SensorPacket:
        """Ambulance siren + approaching vehicle vision + normal IMU/environment."""
        return self.generate_packet(
            audio_class="ambulance",
            audio_conf=0.95,
            vision_class="vehicle",
            vision_conf=0.88,
            imu_impact=False,
            imu_g=1.0,
            temp_c=29.0,
            smoke_ppm=18.0
        )

    def scenario_fire_hazard(self) -> SensorPacket:
        """Visual fire/smoke + high smoke ppm + elevated temperature."""
        return self.generate_packet(
            audio_class="traffic",
            audio_conf=0.60,
            vision_class="fire",
            vision_conf=0.89,
            imu_impact=False,
            imu_g=1.0,
            temp_c=68.5,
            smoke_ppm=280.0
        )

    def scenario_normal_traffic(self) -> SensorPacket:
        """Normal ambient urban background traffic."""
        return self.generate_packet(
            audio_class="traffic",
            audio_conf=0.92,
            vision_class="vehicle",
            vision_conf=0.85,
            imu_impact=False,
            imu_g=1.0,
            temp_c=28.0,
            smoke_ppm=12.0
        )
