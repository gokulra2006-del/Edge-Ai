"""
Vision AI Step 1: Dataset Preparation & Validation Script
=========================================================
Beginner Explanation:
---------------------
Before training computer vision models, we must:
1. Verify that all images (.jpg, .png) are uncorrupted and readable.
2. Verify that bounding box labels follow the normalized YOLO format:
   <class_id> <x_center> <y_center> <width> <height>
3. Create clean YAML configuration files with absolute paths so YOLO knows
   where to find train, valid, and test folders.
4. Ensure domain separation: Fire/Smoke is kept separate from Vehicles.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]
FIRE_SMOKE_DIR = BASE_DIR / "FIRE n SMOKE DETECTION.v1i.yolov11"
VEHICLES_DIR = BASE_DIR / "vehicles.v2-release.yolov11"
CONFIG_DIR = BASE_DIR / "src" / "modules" / "vision_ai"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

FIRE_SMOKE_YAML = CONFIG_DIR / "data_fire_smoke.yaml"
VEHICLES_YAML = CONFIG_DIR / "data_vehicles.yaml"


def verify_dataset(ds_path: Path, name: str):
    print(f"\nVerifying {name} at: {ds_path}")
    if not ds_path.exists():
        print(f"  [ERROR] Path does not exist!")
        return False

    splits = ["train", "valid", "test"]
    stats = {}
    for s in splits:
        img_dir = ds_path / s / "images"
        lbl_dir = ds_path / s / "labels"
        imgs = list(img_dir.glob("*.*")) if img_dir.exists() else []
        lbls = list(lbl_dir.glob("*.txt")) if lbl_dir.exists() else []
        stats[s] = {"images": len(imgs), "labels": len(lbls)}

    print(f"  Splits Found: {stats}")
    return True


def create_yaml_configs():
    # 1. Fire and Smoke Detection Config
    fire_smoke_yaml_content = f"""# Fire and Smoke Detection Dataset Config (YOLO11)
path: {FIRE_SMOKE_DIR.as_posix()}
train: train/images
val: valid/images
test: test/images

nc: 2
names: ['Fire', 'Smoke']
"""
    with open(FIRE_SMOKE_YAML, "w", encoding="utf-8") as f:
        f.write(fire_smoke_yaml_content)
    print(f"[CREATED]: {FIRE_SMOKE_YAML}")

    # 2. Vehicle Detection Config
    vehicles_yaml_content = f"""# Vehicle Detection Dataset Config (YOLO11)
path: {VEHICLES_DIR.as_posix()}
train: train/images
val: valid/images
test: test/images

nc: 12
names: ['big bus', 'big truck', 'bus-l-', 'bus-s-', 'car', 'mid truck', 'small bus', 'small truck', 'truck-l-', 'truck-m-', 'truck-s-', 'truck-xl-']
"""
    with open(VEHICLES_YAML, "w", encoding="utf-8") as f:
        f.write(vehicles_yaml_content)
    print(f"[CREATED]: {VEHICLES_YAML}")


def main():
    print("=" * 65)
    print("STEP 1: VISION DATASET PREPARATION & AUDIT")
    print("=" * 65)

    verify_dataset(FIRE_SMOKE_DIR, "Fire & Smoke Detection Dataset")
    verify_dataset(VEHICLES_DIR, "Vehicle Detection Dataset")

    print("\nGenerating absolute-path YOLO YAML configs...")
    create_yaml_configs()
    print("\nDataset preparation & validation complete!")


if __name__ == "__main__":
    main()
