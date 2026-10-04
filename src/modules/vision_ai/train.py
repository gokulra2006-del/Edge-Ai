"""
Vision AI Step 2: Training Pipeline Script
==========================================
Beginner Explanation:
---------------------
Why YOLO11-nano (YOLO11n)?
1. For an edge computer like the Raspberry Pi 4, standard models (like ResNet50 or YOLOv8x)
   are too heavy (they use too much RAM and run at 1-2 frames per second).
2. YOLO11n (Nano) is specifically designed for mobile and edge robotics:
   - Size: Only ~5.5 MB (2.6 million parameters)
   - Input size: 320x320 pixels
   - Real-time latency: Can run at 10-15+ FPS on edge CPUs.
3. In this script, we take pre-trained edge weights (yolo11n.pt) and fine-tune them
   on our Fire and Smoke dataset so the model specializes in urban hazard detection.
"""
import os
import sys
import shutil
from pathlib import Path
from ultralytics import YOLO

BASE_DIR = Path(__file__).resolve().parents[3]
DATA_YAML = BASE_DIR / "src" / "modules" / "vision_ai" / "data_fire_smoke.yaml"
OUTPUT_MODEL_DIR = BASE_DIR / "models" / "vision"
OUTPUT_MODEL_DIR.mkdir(parents=True, exist_ok=True)
TARGET_BEST_WEIGHTS = OUTPUT_MODEL_DIR / "fire_smoke_best.pt"


def train_fire_smoke(epochs: int = 5, imgsz: int = 320, batch: int = 16):
    print("=" * 65)
    print("STEP 2: VISION AI TRAINING (YOLO11n Fire & Smoke Detection)")
    print("=" * 65)

    if not DATA_YAML.exists():
        print(f"Error: {DATA_YAML} not found. Run dataset_prep.py first!")
        return

    # Load from existing best weights for fine-tuning if available, otherwise base yolo11n.pt
    starting_weights = str(TARGET_BEST_WEIGHTS) if TARGET_BEST_WEIGHTS.exists() else "yolo11n.pt"
    print(f"Loading weights from: {starting_weights}...")
    model = YOLO(starting_weights)

    print(f"Starting training on CPU (Epochs: {epochs}, Image Size: {imgsz}, Batch: {batch})...")
    # Train model
    results = model.train(
        data=str(DATA_YAML),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device="cpu",
        workers=0,
        project="runs_fire_smoke",
        name="train_job",
        exist_ok=True,
        verbose=True
    )

    # Locate and copy best weights
    best_weights = Path(results.save_dir) / "weights" / "best.pt"
    if best_weights.exists():
        shutil.copy(str(best_weights), str(TARGET_BEST_WEIGHTS))
        print(f"\n[SUCCESS] Trained model weights saved to: {TARGET_BEST_WEIGHTS} ({os.path.getsize(TARGET_BEST_WEIGHTS)/(1024*1024):.2f} MB)")
    else:
        last_weights = Path(results.save_dir) / "weights" / "last.pt"
        if last_weights.exists():
            shutil.copy(str(last_weights), str(TARGET_BEST_WEIGHTS))
            print(f"\n[SUCCESS] Model weights saved to: {TARGET_BEST_WEIGHTS}")

    print("Vision training pipeline completed!")


if __name__ == "__main__":
    train_fire_smoke(epochs=8, imgsz=320, batch=16)
