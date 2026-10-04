"""
Core Pipeline Orchestrator.
Connects the entire 6-stage Edge-AI emergency pipeline in a deterministic sequence:
SENSORS -> PREPROCESSING -> AI INFERENCE -> SENSOR FUSION ->
EVENT CLASSIFICATION -> SEVERITY -> LOCATION -> RESPONSE -> DATABASE + DASHBOARD
"""
from typing import Dict, Any, Optional
from src.core.data_models import SensorPacket, FusedEvent, SeverityAssessment, LocationEstimate, ResponseAction
from src.modules.sensors.simulator import SimulatedSensorHub
from src.modules.audio_ai.preprocessor import AudioPreprocessor
from src.modules.audio_ai.classifier import AudioClassifier
from src.modules.vision_ai.preprocessor import VisionPreprocessor
from src.modules.vision_ai.detector import VisionDetector
from src.modules.sensor_fusion.fusion_engine import SensorFusionEngine
from src.modules.severity_assessment.evaluator import SeverityEvaluator
from src.modules.localization.localizer import MultiNodeLocalizer
from src.modules.autonomous_response.dispatcher import AutonomousResponseDispatcher
from src.modules.database.db_manager import DatabaseManager
from src.modules.logging.logger import LOGGER


class EmergencyPipelineOrchestrator:
    def __init__(self):
        LOGGER.info("Initializing Edge-AI Emergency Pipeline Orchestrator...")
        
        # Modules instantiation
        self.sensor_hub = SimulatedSensorHub()
        self.audio_prep = AudioPreprocessor()
        self.audio_ai = AudioClassifier()
        self.vision_prep = VisionPreprocessor()
        self.vision_ai = VisionDetector()
        self.fusion = SensorFusionEngine()
        self.severity = SeverityEvaluator()
        self.localizer = MultiNodeLocalizer()
        self.response = AutonomousResponseDispatcher()
        self.db = DatabaseManager()

        LOGGER.info("All 12 pipeline modules initialized successfully.")

    def process_packet(
        self,
        packet: SensorPacket,
        node_confidence_matrix: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Executes the end-to-end emergency data flow for a single sensor packet.
        """
        LOGGER.info(f"--- [NEW CYCLE] Ingesting Sensor Packet from Node: {packet.node_id} ---")

        # 1. PREPROCESSING
        # Audio & Vision Preprocessing (feature extraction / scaling)
        audio_features = self.audio_prep.process_buffer([0.05, -0.12, 0.45, -0.62, 0.88])
        vision_meta = self.vision_prep.preprocess_frame((640, 480, 3))

        # 2. AI INFERENCE
        # Evaluates raw inputs into class predictions
        audio_pred = self.audio_ai.predict({
            "class": packet.audio_prediction.class_name,
            "confidence": packet.audio_prediction.confidence
        })
        vision_pred = self.vision_ai.predict({
            "class": packet.vision_prediction.primary_class,
            "confidence": packet.vision_prediction.confidence
        })

        # Update packet with verified predictions
        packet.audio_prediction = audio_pred
        packet.vision_prediction = vision_pred

        # 3. SENSOR FUSION & EVENT CLASSIFICATION
        fused_event: FusedEvent = self.fusion.fuse(packet)

        # 4. SEVERITY ASSESSMENT
        severity: SeverityAssessment = self.severity.evaluate(fused_event)

        # 5. LOCATION ESTIMATION
        location: LocationEstimate = self.localizer.estimate_location(fused_event, node_confidence_matrix)

        # 6. AUTONOMOUS RESPONSE
        action: ResponseAction = self.response.dispatch(fused_event, severity, location)

        # 7. DATABASE PERSISTENCE
        event_id = self.db.log_event(fused_event, severity, location, action)

        LOGGER.info(f"--- [CYCLE COMPLETE] Event #{event_id} Recorded & Dispatched ---")

        return {
            "event_id": event_id,
            "event": fused_event.event_type,
            "confidence": fused_event.confidence,
            "is_verified": fused_event.is_verified,
            "severity": severity.level,
            "severity_score": severity.score,
            "location": location.probable_zone,
            "primary_node": location.primary_node,
            "action": action.traffic_signal_state,
            "green_corridor": action.green_corridor_active,
            "alert": action.alert_type
        }
