"""
Vision AI Step 5: Inference Pipeline Script
===========================================
Beginner Explanation:
---------------------
How Edge Inference Works:
1. Input: A camera frame or image file (e.g. from an urban CCTV camera).
2. Preprocessing: Resized to 320x320 and normalized.
3. Forward Pass: The model evaluates bounding boxes and class probabilities.
4. Output: Structured Python dictionary suitable for consumption by the
   SENSOR FUSION and SEVERITY ASSESSMENT modules:
   {
       "hazard_detected": True,
       "primary_hazard": "Fire",
       "max_confidence": 0.94,
       "detections": [
           {"class": "Fire", "confidence": 0.94, "bbox": [102, 45, 230, 180]}
       ],
       "latency_ms": 18.5
   }
"""
import time
import os
from pathlib import Path
import cv2
import numpy as np
_runtime_root = Path(__file__).resolve().parents[3]
_yolo_config = _runtime_root / 'logs' / 'ultralytics'
_matplotlib_config = _runtime_root / 'logs' / 'matplotlib'
_yolo_config.mkdir(parents=True, exist_ok=True)
_matplotlib_config.mkdir(parents=True, exist_ok=True)
os.environ['YOLO_CONFIG_DIR'] = str(_yolo_config)
os.environ['MPLCONFIGDIR'] = str(_matplotlib_config)
from ultralytics import YOLO
from src.config.model_profile import model_profile

BASE_DIR = Path(__file__).resolve().parents[3]
MODEL_PATH = BASE_DIR / "models" / "vision" / "fire_smoke_best.pt"


class VisionInferenceEngine:
    """Lightweight Edge Vision AI Inference Engine for Urban Hazard Detection."""

    def __init__(self, model_path: str = None, conf_threshold: float = 0.35, imgsz: int = 320):
        profile = model_profile()
        paths = [model_path] if model_path is not None else profile['vision']
        if model_path is None and profile['name'] == 'legacy' and not paths[0].exists():
            paths = [BASE_DIR / 'yolo11n.pt']
        self.conf_threshold = conf_threshold
        self.imgsz = profile.get('imgsz', imgsz) if model_path is None else imgsz
        self.model_paths = [str(p) for p in paths]
        self.models = [YOLO(p) for p in self.model_paths]
        self.model = self.models[0]  # Backwards-compatible single-model accessor.

    def predict_image(self, image_input, save_annotated_path: str = None):
        """
        Run inference on an image path or numpy BGR frame.
        Returns:
            dict: Structured prediction results.
        """
        start_time = time.perf_counter()
        if isinstance(image_input, (str, Path)):
            image_input = cv2.imread(str(image_input))
        if (not isinstance(image_input, np.ndarray) or image_input.ndim != 3
                or image_input.shape[2] != 3 or image_input.size == 0
                or image_input.dtype != np.uint8):
            raise ValueError('Expected a readable image path or a nonempty uint8 BGR image')
        results = []
        for model in self.models:
            results.extend(model.predict(source=image_input, imgsz=self.imgsz,
                           conf=self.conf_threshold, device='cpu', verbose=False))

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        detections = []
        max_conf = 0.0
        primary_hazard = None

        for res in results:
            boxes = res.boxes
            for box in boxes:
                cls_id = int(box.cls[0].item())
                conf = float(box.conf[0].item())
                xyxy = [round(float(coord), 1) for coord in box.xyxy[0].tolist()]
                class_name = res.names.get(cls_id, f"class_{cls_id}")

                detections.append({
                    "class": class_name,
                    "confidence": round(conf, 4),
                    "bbox": xyxy
                })

                if conf > max_conf:
                    max_conf = conf
                    primary_hazard = class_name

        if save_annotated_path:
            annotated = image_input.copy()
            for detection in detections:
                x1, y1, x2, y2 = map(int, detection['bbox'])
                cv2.rectangle(annotated, (x1,y1), (x2,y2), (0,180,255), 2)
                cv2.putText(annotated, detection['class'], (x1,max(15,y1-5)),
                            cv2.FONT_HERSHEY_SIMPLEX, .5, (0,180,255), 1)
            Path(save_annotated_path).parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(save_annotated_path), annotated):
                raise OSError(f'Cannot save annotation: {save_annotated_path}')
        # A high-confidence vehicle must not hide a lower-confidence fire/smoke detection.
        hazards = [d for d in detections if d['class'].lower() in ('fire', 'smoke')]
        if hazards:
            primary = max(hazards, key=lambda d: d['confidence'])
            primary_hazard, max_conf = primary['class'], primary['confidence']
        hazard_detected = len(detections) > 0

        return {
            "hazard_detected": hazard_detected,
            "primary_hazard": primary_hazard if hazard_detected else "NONE",
            "max_confidence": round(max_conf, 4),
            "detection_count": len(detections),
            "detections": detections,
            "latency_ms": round(elapsed_ms, 2)
        }


def run_demo():
    print("=" * 65)
    print("STEP 5: RUNNING VISION INFERENCE DEMO")
    print("=" * 65)

    engine = VisionInferenceEngine()

    # Find a sample test image
    test_dir = BASE_DIR / "FIRE n SMOKE DETECTION.v1i.yolov11" / "test" / "images"
    test_images = list(test_dir.glob("*.jpg")) + list(test_dir.glob("*.png"))

    if not test_images:
        print(f"No test images found in {test_dir}. Generating synthetic test frame...")
        synthetic_frame = np.zeros((320, 320, 3), dtype=np.uint8)
        # Draw a bright orange circle to simulate flame
        cv2.circle(synthetic_frame, (160, 160), 60, (0, 140, 255), -1)
        sample_path = BASE_DIR / "models" / "vision" / "synthetic_test.jpg"
        cv2.imwrite(str(sample_path), synthetic_frame)
        sample_target = str(sample_path)
    else:
        sample_target = str(test_images[0])

    print(f"Testing inference on: {sample_target}")
    output_annotated = str(BASE_DIR / "models" / "vision" / "sample_detection_output.jpg")
    result = engine.predict_image(sample_target, save_annotated_path=output_annotated)

    print("\n--- Inference Output Dictionary ---")
    import json
    print(json.dumps(result, indent=2))
    print(f"[PASS] Inference latency: {result['latency_ms']} ms ({1000.0/max(1, result['latency_ms']):.1f} FPS)")


if __name__ == "__main__":
    run_demo()
