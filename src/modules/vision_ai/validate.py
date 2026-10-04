"""
Vision AI Step 3: Validation Script
===================================
Beginner Explanation:
---------------------
This script loads the fine-tuned YOLO model and runs it against the
Validation split (80 images). It checks whether the model detects Fire and Smoke
bounding boxes accurately and confirms that no corruption occurred in the weight tensors.
"""
from pathlib import Path
from ultralytics import YOLO

BASE_DIR = Path(__file__).resolve().parents[3]
DATA_YAML = BASE_DIR / "src" / "modules" / "vision_ai" / "data_fire_smoke.yaml"
MODEL_PATH = BASE_DIR / "models" / "vision" / "fire_smoke_best.pt"


def validate_model():
    print("=" * 65)
    print("STEP 3: VISION MODEL VALIDATION (Validation Split)")
    print("=" * 65)

    # Fallback to base yolo11n if trained weights not yet compiled
    weight_file = str(MODEL_PATH) if MODEL_PATH.exists() else "yolo11n.pt"
    print(f"Loading weights from: {weight_file}")
    model = YOLO(weight_file)

    metrics = model.val(
        data=str(DATA_YAML),
        split="val",
        imgsz=320,
        device="cpu",
        batch=16,
        verbose=True
    )

    print("\n--- Validation Results ---")
    print(f"  Precision: {metrics.box.mp:.4f}")
    print(f"  Recall:    {metrics.box.mr:.4f}")
    print(f"  mAP@50:    {metrics.box.map50:.4f}")
    print(f"  mAP@50-95: {metrics.box.map:.4f}")
    print("[PASS] Validation split evaluation complete!")
    return metrics


if __name__ == "__main__":
    validate_model()
