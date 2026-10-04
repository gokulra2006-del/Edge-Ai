"""
Module 4: Sensor Fusion & Multi-Modal Event Classification Engine.
Correlates evidence across Audio, Vision, IMU, and Environmental sensors
to produce verified, high-confidence emergency events.
"""
from datetime import datetime
from typing import List, Optional
from src.core.data_models import SensorPacket, FusedEvent
from src.config.settings import CONFIG
from src.modules.logging.logger import LOGGER


class SensorFusionEngine:
    def __init__(self, config=CONFIG):
        self.config = config

    def fuse(self, packet: SensorPacket) -> FusedEvent:
        """
        Executes multi-sensor fusion pipeline on the incoming sensor packet.
        """
        audio = packet.audio_prediction
        vision = packet.vision_prediction
        imu = packet.imu_reading
        env = packet.environment

        contributing: List[str] = []
        event_type = "NORMAL"
        confidence = 0.50
        is_verified = False

        # --- RULE 1: ROAD ACCIDENT / VEHICLE COLLISION ---
        # Triggered by acoustic crash, verified by IMU impact and/or vehicle visual evidence
        if audio.class_name == "crash" and audio.confidence >= 0.60:
            contributing.append("audio")
            
            # Check IMU corroboration
            has_imu_impact = imu.impact_detected or imu.g_force >= self.config.impact_g_threshold
            if has_imu_impact:
                contributing.append("imu")

            # Check Vision corroboration (presence of vehicles)
            vehicle_classes = ["vehicle", "car", "bus", "truck", "big truck", "small truck"]
            has_vehicle_vision = vision.primary_class.lower() in vehicle_classes and vision.confidence >= 0.50
            if has_vehicle_vision:
                contributing.append("vision")

            # Calculate weighted multi-modal confidence
            w_aud = self.config.w_audio_crash
            w_imu = self.config.w_imu_impact
            w_vis = self.config.w_vision_vehicle

            conf_aud = audio.confidence
            conf_imu = imu.confidence if has_imu_impact else 0.10
            conf_vis = vision.confidence if has_vehicle_vision else 0.20

            confidence = (w_aud * conf_aud) + (w_imu * conf_imu) + (w_vis * conf_vis)
            event_type = "ACCIDENT"
            is_verified = len(contributing) >= 2  # Requires at least 2 modalities

        # --- RULE 2: EMERGENCY VEHICLE (AMBULANCE / FIRETRUCK / POLICE) ---
        elif audio.class_name in ["ambulance", "firetruck", "police", "siren"] and audio.confidence >= 0.65:
            contributing.append("audio")
            
            # Corroborate with camera presence of traffic or vehicle
            has_vehicle_vision = vision.primary_class.lower() in ["vehicle", "car", "bus", "truck"]
            if has_vehicle_vision:
                contributing.append("vision")

            w_aud = self.config.w_audio_siren
            w_vis = self.config.w_vision_siren
            conf_vis = vision.confidence if has_vehicle_vision else 0.50

            confidence = (w_aud * audio.confidence) + (w_vis * conf_vis)
            event_type = "EMERGENCY_VEHICLE"
            is_verified = True

        # --- RULE 3: FIRE AND SMOKE HAZARD ---
        elif (vision.primary_class.lower() in ["fire", "smoke"] and vision.confidence >= 0.65) or \
             env.temperature_c >= self.config.high_temp_threshold_c or \
             env.smoke_ppm >= self.config.critical_smoke_threshold_ppm:

            if vision.primary_class.lower() in ["fire", "smoke"]:
                contributing.append("vision")
            if env.temperature_c >= self.config.high_temp_threshold_c or env.smoke_ppm >= self.config.critical_smoke_threshold_ppm:
                contributing.append("environment")

            conf_vis = vision.confidence if "vision" in contributing else 0.40
            conf_env = min(1.0, (env.smoke_ppm / 200.0) * 0.5 + (env.temperature_c / 80.0) * 0.5)

            confidence = (self.config.w_vision_fire * conf_vis) + (self.config.w_env_fire * conf_env)
            event_type = "FIRE_HAZARD"
            is_verified = len(contributing) >= 2

        # --- RULE 4: ROAD OBSTACLE (Pothole, Animal, Construction) ---
        elif vision.primary_class.lower() in ["pothole", "animal", "construction board"] and vision.confidence >= 0.70:
            contributing.append("vision")
            event_type = "ROAD_HAZARD"
            confidence = vision.confidence
            is_verified = True

        # --- DEFAULT: NORMAL TRAFFIC ---
        else:
            event_type = "NORMAL"
            confidence = 0.90
            contributing.append("baseline")
            is_verified = True

        fused = FusedEvent(
            timestamp=datetime.now().isoformat(),
            event_type=event_type,
            confidence=round(confidence, 4),
            contributing_modalities=contributing,
            is_verified=is_verified,
            raw_packet=packet
        )

        LOGGER.info(
            f"Fusion Decision: Event={fused.event_type} | "
            f"Confidence={fused.confidence:.2f} | "
            f"Modalities={fused.contributing_modalities} | Verified={fused.is_verified}"
        )
        return fused
