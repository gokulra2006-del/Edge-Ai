"""
Vision AI Step 4: Independent Test Evaluation Script
===================================================
Beginner Explanation:
---------------------
Why a separate test evaluation?
1. Training Split: The model learns from these images.
2. Validation Split: Used during training to check overfitting.
3. Test Split (Held-out): These images were NEVER seen during training.
   Evaluating on the test split proves that the model genuinely generalizes
   to new, unseen emergency situations in the real world.

Key Edge AI Metrics Computed:
- Precision (P): Out of all detections made, what percentage were real hazards? (Avoids false alarms)
- Recall (R): Out of all real hazards present, what percentage did the model detect? (Critical: cannot miss a real fire!)
- mAP@50: Mean Average Precision at Intersection over Union (IoU) threshold of 0.50.
- mAP@50-95: Standard COCO benchmark mAP across IoU thresholds from 0.50 to 0.95.
- Inference Latency (ms): Time required to process a single 320x320 frame on the CPU.
- FPS (Frames Per Second): 1000 / Latency (ms). For Raspberry Pi 4 edge deployment, >10 FPS is required for real-time safety.
"""
import json
import time
from pathlib import Path
from ultralytics import YOLO

BASE_DIR = Path(__file__).resolve().parents[3]
DATA_YAML = BASE_DIR / "src" / "modules" / "vision_ai" / "data_fire_smoke.yaml"
MODEL_PATH = BASE_DIR / "models" / "vision" / "fire_smoke_best.pt"
METRICS_OUT = BASE_DIR / "models" / "vision" / "evaluation_report.json"


def evaluate_test_set(weight_path: str = None, imgsz: int = 320):
    print("=" * 65)
    print("STEP 4: INDEPENDENT TEST SET EVALUATION (Unseen Test Split)")
    print("=" * 65)

    if weight_path is None:
        weight_path = str(MODEL_PATH) if MODEL_PATH.exists() else "yolo11n.pt"

    print(f"Loading weights: {weight_path}")
    model = YOLO(weight_path)

    # 1. Run Ultralytics evaluation on split='test'
    print(f"Running evaluation on test split (imgsz={imgsz}, device='cpu')...")
    metrics = model.val(
        data=str(DATA_YAML),
        split="test",
        imgsz=imgsz,
        device="cpu",
        batch=1,  # Batch=1 simulates real-time edge streaming
        verbose=True
    )

    # 2. Extract standard Object Detection metrics
    precision = float(metrics.box.mp)
    recall = float(metrics.box.mr)
    map50 = float(metrics.box.map50)
    map50_95 = float(metrics.box.map)

    # Latency breakdowns (ms) from speed dictionary
    preprocess_ms = float(metrics.speed.get("preprocess", 0.0))
    inference_ms = float(metrics.speed.get("inference", 0.0))
    postprocess_ms = float(metrics.speed.get("postprocess", 0.0))
    total_latency_ms = preprocess_ms + inference_ms + postprocess_ms
    fps = round(1000.0 / total_latency_ms, 2) if total_latency_ms > 0 else 0.0

    # 3. Class-specific metrics
    per_class_metrics = {}
    if hasattr(metrics.box, 'p') and hasattr(metrics.box, 'r'):
        class_names = metrics.names
        for idx, cls_id in enumerate(metrics.box.ap_class_index):
            name = class_names[cls_id]
            per_class_metrics[name] = {
                "precision": round(float(metrics.box.p[idx]), 4),
                "recall": round(float(metrics.box.r[idx]), 4),
                "ap50": round(float(metrics.box.ap50[idx]), 4),
                "ap50_95": round(float(metrics.box.ap[idx]), 4)
            }

    report = {
        "model_architecture": "YOLO11-nano (YOLO11n)",
        "task": "Object Detection",
        "dataset": "FIRE n SMOKE DETECTION (Roboflow v1i)",
        "classes": ["Fire", "Smoke"],
        "input_resolution": f"{imgsz}x{imgsz}",
        "hardware_target": "Raspberry Pi 4 Quad-Core Cortex-A72 CPU",
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "mAP_50": round(map50, 4),
        "mAP_50_95": round(map50_95, 4),
        "latency_breakdown_ms": {
            "preprocess_ms": round(preprocess_ms, 2),
            "inference_ms": round(inference_ms, 2),
            "postprocess_ms": round(postprocess_ms, 2),
            "total_latency_ms": round(total_latency_ms, 2)
        },
        "frames_per_second_fps": fps,
        "class_breakdown": per_class_metrics
    }

    METRICS_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(METRICS_OUT, "w") as f:
        json.dump(report, f, indent=4)

    print("\n" + "=" * 65)
    print("FINAL TEST EVALUATION SUMMARY")
    print("=" * 65)
    print(f"  Precision:      {precision * 100:.2f}%")
    print(f"  Recall:         {recall * 100:.2f}%")
    print(f"  mAP@50:         {map50 * 100:.2f}%")
    print(f"  mAP@50-95:      {map50_95 * 100:.2f}%")
    print(f"  Total Latency:  {total_latency_ms:.2f} ms / frame")
    print(f"  Edge FPS:       {fps} FPS")
    print(f"  Saved Report:   {METRICS_OUT}")
    print("=" * 65)
    return report


if __name__ == "__main__":
    evaluate_test_set()
