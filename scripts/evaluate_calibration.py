import argparse
import json
from pathlib import Path
import random
import sys
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.modules.calibration.calibration_engine import (
    IsotonicCalibrator,
    TemperatureScalingCalibrator,
    compute_calibration_metrics,
)


def run_calibration_evaluation(seed: int = 42) -> Dict[str, Any]:
    rng = random.Random(seed)
    n = 200

    # 1. Synthesize uncalibrated probabilities with typical edge neural network overconfidence
    raw_confs: List[float] = []
    labels: List[int] = []

    for _ in range(n):
        # Ground truth probability
        p_true = rng.uniform(0.1, 0.9)
        y = 1 if rng.random() < p_true else 0
        # Overconfidence distortion: p_pred pushes closer to 0 or 1
        p_pred = 0.5 + (p_true - 0.5) * 1.5
        p_pred = max(0.05, min(0.95, p_pred))
        raw_confs.append(round(p_pred, 3))
        labels.append(y)

    # 2. Strict 50/50 split: Calibration vs Held-out Test (Zero leakage)
    split_idx = n // 2
    calib_confs, test_confs = raw_confs[:split_idx], raw_confs[split_idx:]
    calib_y, test_y = labels[:split_idx], labels[split_idx:]

    # 3. Fit calibrators on calibration split ONLY
    temp_calib = TemperatureScalingCalibrator(model_version="edge-vision-v1")
    temp_calib.fit(calib_confs, calib_y)

    iso_calib = IsotonicCalibrator(model_version="edge-vision-v1")
    iso_calib.fit(calib_confs, calib_y)

    # 4. Evaluate on held-out test split
    uncalib_metrics = compute_calibration_metrics(test_confs, test_y)

    temp_test_confs = [temp_calib.calibrate(c) for c in test_confs]
    temp_metrics = compute_calibration_metrics(temp_test_confs, test_y)

    iso_test_confs = [iso_calib.calibrate(c) for c in test_confs]
    iso_metrics = compute_calibration_metrics(iso_test_confs, test_y)

    results = {
        "dataset_size": n,
        "calibration_split_size": split_idx,
        "test_split_size": n - split_idx,
        "learned_temperature": temp_calib.temperature,
        "uncalibrated": uncalib_metrics.to_dict(),
        "temperature_scaling": temp_metrics.to_dict(),
        "isotonic_regression": iso_metrics.to_dict(),
    }

    print("=================================================================")
    print(" Phase 6C Confidence Calibration Comparison Report (Held-Out Test)")
    print("=================================================================")
    print(f"Sample Count: {len(test_confs)} | Learned Temp: {temp_calib.temperature:.3f}\n")
    print(f"{'Method':<22} | {'ECE':<8} | {'MCE':<8} | {'Brier':<8} | {'Calib Quality'}")
    print("-" * 65)
    print(f"{'Uncalibrated':<22} | {uncalib_metrics.ece:<8.4f} | {uncalib_metrics.mce:<8.4f} | {uncalib_metrics.brier_score:<8.4f} | {uncalib_metrics.calibration_quality:.4f}")
    print(f"{'Temperature Scaling':<22} | {temp_metrics.ece:<8.4f} | {temp_metrics.mce:<8.4f} | {temp_metrics.brier_score:<8.4f} | {temp_metrics.calibration_quality:.4f}")
    print(f"{'Isotonic Regression':<22} | {iso_metrics.ece:<8.4f} | {iso_metrics.mce:<8.4f} | {iso_metrics.brier_score:<8.4f} | {iso_metrics.calibration_quality:.4f}")
    print("=================================================================")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    run_calibration_evaluation(seed=args.seed)
