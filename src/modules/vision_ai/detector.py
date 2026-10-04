"""
Module 3: Vision AI Detector.
Interface for edge object detection (vehicles, fire, smoke, road hazards).
"""
from typing import Dict, Any, List, Optional
from src.core.data_models import VisionPrediction
from src.modules.logging.logger import LOGGER


class VisionDetector:
    """
    Interface for Raspberry Pi 4 edge camera detection.
    Wraps YOLO11-nano / YOLOv8n TFLite or simulated detector.
    """
    CLASSES = ["vehicle", "car", "bus", "truck", "fire", "smoke", "pothole", "animal", "pedestrian"]

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path
        self._inference_engine = None
        LOGGER.info(f"VisionDetector initialized (Model path: {model_path or 'Simulated Engine'})")

    def _get_engine(self):
        if self._inference_engine is None:
            try:
                from src.modules.vision_ai.inference import VisionInferenceEngine
                self._inference_engine = VisionInferenceEngine(model_path=self.model_path)
            except Exception as e:
                from src.config.model_profile import model_profile
                if model_profile()['name'] != 'legacy':
                    raise
                LOGGER.warning(f"Could not load VisionInferenceEngine: {e}. Falling back to simulation.")
        return self._inference_engine

    def predict_image(self, image_input) -> VisionPrediction:
        """
        Run inference directly on a camera frame or image file path.
        Returns:
            VisionPrediction data model instance.
        """
        engine = self._get_engine()
        if engine is not None:
            res = engine.predict_image(image_input)
            classes = [d["class"] for d in res["detections"]] if res["detections"] else ["safe"]
            primary = res["primary_hazard"] if res["hazard_detected"] else "normal"
            bboxes = [{"class": d["class"], "confidence": d["confidence"], "box": d["bbox"]} for d in res["detections"]]
            return VisionPrediction(
                detected_classes=classes,
                primary_class=primary,
                confidence=res["max_confidence"],
                bounding_boxes=bboxes
            )
        return self.predict({"class": "safe", "confidence": 0.99})

    @staticmethod
    def classify_smoke_context(detected_classes: List[str], bounding_boxes: Optional[List[Dict[str, Any]]] = None) -> str:
        """
        Differentiates vehicle exhaust / car smoke from structural / wildfire smoke.
        
        Returns:
            'VEHICLE_SMOKE': When smoke is observed in proximity to cars/trucks/buses without flames.
            'FIRE_SMOKE': When smoke is accompanied by open flame or elevated fire hazard.
            'UNCONFIRMED_SMOKE': When smoke is observed alone in open frame.
            'NONE': When no smoke is detected.
        """
        classes_lower = [c.lower() for c in detected_classes]
        has_smoke = any("smoke" in c for c in classes_lower)
        has_fire = any(c in classes_lower for c in ("fire", "flame"))
        vehicle_terms = ("car", "vehicle", "bus", "truck", "big truck", "small truck", "motorcycle")
        has_vehicle = any(any(v in c for v in vehicle_terms) for c in classes_lower)

        if not has_smoke:
            return "NONE"
        if has_fire:
            return "FIRE_SMOKE"
        if has_vehicle:
            return "VEHICLE_SMOKE"
        return "UNCONFIRMED_SMOKE"

    def predict(self, prediction_dict: Dict[str, Any]) -> VisionPrediction:
        """
        Accepts standardized prediction dictionary and converts to typed VisionPrediction.
        Example: {"class": "vehicle", "confidence": 0.91}
        """
        primary = prediction_dict.get("class", "vehicle")
        conf = float(prediction_dict.get("confidence", 0.85))
        bboxes = prediction_dict.get("bounding_boxes", [
            {"class": primary, "confidence": conf, "box": [0.2, 0.3, 0.6, 0.7]}
        ])
        det_classes = prediction_dict.get("detected_classes", [primary])
        return VisionPrediction(
            detected_classes=det_classes,
            primary_class=primary,
            confidence=conf,
            bounding_boxes=bboxes
        )
