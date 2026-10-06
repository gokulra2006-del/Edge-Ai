"""Confidence Calibration Engine (Phase 6C).

Implements:
- Temperature scaling & Isotonic regression fit only on held-out calibration data.
- Reliability diagrams, Expected Calibration Error (ECE), Maximum Calibration Error (MCE), Brier score.
- Per-class, by-device, by-zone, and pre/post drift calibration metrics.
- OOD confidence capping rule (never allow 100% confidence on OOD).
- Integration hook for calibration_quality into Phase 6B risk computation.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

CalibrationMethod = Literal["uncalibrated", "temperature", "isotonic"]


@dataclass
class ReliabilityBin:
    bin_idx: int
    bin_lower: float
    bin_upper: float
    confidence_mean: float
    accuracy_mean: float
    sample_count: int


@dataclass
class CalibrationMetrics:
    ece: float
    mce: float
    brier_score: float
    sample_count: int
    bins: List[ReliabilityBin]
    calibration_quality: float  # max(0.0, 1.0 - ECE)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ece": self.ece,
            "mce": self.mce,
            "brier_score": self.brier_score,
            "sample_count": self.sample_count,
            "calibration_quality": self.calibration_quality,
            "bins": [asdict(b) for b in self.bins],
        }


def compute_calibration_metrics(
    confidences: List[float],
    accuracies: List[int],  # 1 if prediction matches ground truth, 0 otherwise
    num_bins: int = 10,
) -> CalibrationMetrics:
    """
    Computes Expected Calibration Error (ECE), MCE, Brier score, and reliability diagram bins.
    """
    n = len(confidences)
    if n == 0 or len(accuracies) != n:
        return CalibrationMetrics(0.0, 0.0, 0.0, 0, [], 1.0)

    # 1. Brier score = 1/N sum((p_i - y_i)^2)
    brier = sum((p - y) ** 2 for p, y in zip(confidences, accuracies)) / n

    # 2. Equal-width binning
    bins: List[ReliabilityBin] = []
    ece = 0.0
    mce = 0.0
    bin_width = 1.0 / num_bins

    for m in range(num_bins):
        b_low = m * bin_width
        b_high = (m + 1) * bin_width
        # Include boundary on last bin
        if m == num_bins - 1:
            indices = [i for i, p in enumerate(confidences) if b_low <= p <= b_high]
        else:
            indices = [i for i, p in enumerate(confidences) if b_low <= p < b_high]

        count = len(indices)
        if count > 0:
            conf_mean = sum(confidences[i] for i in indices) / count
            acc_mean = sum(accuracies[i] for i in indices) / count
            gap = abs(acc_mean - conf_mean)
            ece += (count / n) * gap
            if gap > mce:
                mce = gap
        else:
            conf_mean = (b_low + b_high) / 2.0
            acc_mean = 0.0

        bins.append(
            ReliabilityBin(
                bin_idx=m,
                bin_lower=round(b_low, 3),
                bin_upper=round(b_high, 3),
                confidence_mean=round(conf_mean, 4),
                accuracy_mean=round(acc_mean, 4),
                sample_count=count,
            )
        )

    calib_qual = max(0.0, min(1.0, 1.0 - ece))

    return CalibrationMetrics(
        ece=round(ece, 4),
        mce=round(mce, 4),
        brier_score=round(brier, 4),
        sample_count=n,
        bins=bins,
        calibration_quality=round(calib_qual, 4),
    )


class TemperatureScalingCalibrator:
    """
    Learns single temperature parameter T > 0 on logits / uncalibrated confidences.
    """

    def __init__(self, temperature: float = 1.0, model_version: str = "v1.0"):
        self.temperature = max(0.01, temperature)
        self.model_version = model_version
        self.fitted = False

    def fit(self, confidences: List[float], labels: List[int]) -> "TemperatureScalingCalibrator":
        """
        Finds optimal temperature T minimizing negative log likelihood via bounded grid/golden section.
        Strictly requires held-out calibration split.
        """
        if len(confidences) < 4 or len(confidences) != len(labels):
            self.temperature = 1.0
            self.fitted = True
            return self

        best_t = 1.0
        best_nll = float("inf")

        # Grid search over temperatures from 0.2 to 5.0
        t_candidates = [0.2 + i * 0.05 for i in range(96)]
        for t in t_candidates:
            nll = 0.0
            for p, y in zip(confidences, labels):
                p_clamped = max(1e-6, min(1.0 - 1e-6, p))
                logit = math.log(p_clamped / (1.0 - p_clamped))
                scaled_logit = logit / t
                scaled_p = 1.0 / (1.0 + math.exp(-scaled_logit))
                scaled_p = max(1e-6, min(1.0 - 1e-6, scaled_p))
                loss = -(math.log(scaled_p) if y == 1 else math.log(1.0 - scaled_p))
                nll += loss

            if nll < best_nll:
                best_nll = nll
                best_t = t

        self.temperature = round(best_t, 3)
        self.fitted = True
        return self

    def calibrate(self, confidence: float, is_ood: bool = False) -> float:
        # Safety invariant: OOD input must be capped and never allowed 100% confidence
        if is_ood:
            return min(0.35, confidence * 0.40)

        p = max(1e-6, min(1.0 - 1e-6, confidence))
        logit = math.log(p / (1.0 - p))
        scaled_logit = logit / self.temperature
        scaled_p = 1.0 / (1.0 + math.exp(-scaled_logit))
        return round(max(0.0, min(1.0, scaled_p)), 4)


class IsotonicCalibrator:
    """
    Non-parametric piecewise constant calibrator fit via Pool Adjacent Violators (PAV).
    """

    def __init__(self, model_version: str = "v1.0"):
        self.model_version = model_version
        self.breakpoints: List[Tuple[float, float]] = []
        self.fitted = False

    def fit(self, confidences: List[float], labels: List[int]) -> "IsotonicCalibrator":
        if len(confidences) < 4:
            self.breakpoints = [(0.0, 0.0), (1.0, 1.0)]
            self.fitted = True
            return self

        # Sort pairs by confidence
        pairs = sorted(zip(confidences, labels), key=lambda x: x[0])
        # PAV algorithm: blocks of (weight, value, sum_conf, count)
        blocks: List[List[float]] = []  # [sum_y, weight, mean_conf]
        for c, y in pairs:
            blocks.append([float(y), 1.0, float(c)])
            while len(blocks) >= 2 and (blocks[-2][0] / blocks[-2][1]) >= (blocks[-1][0] / blocks[-1][1]):
                b2 = blocks.pop()
                b1 = blocks.pop()
                blocks.append([b1[0] + b2[0], b1[1] + b2[1], (b1[2] * b1[1] + b2[2] * b2[1]) / (b1[1] + b2[1])])

        self.breakpoints = [(round(b[2] / b[1], 4), round(b[0] / b[1], 4)) for b in blocks]
        self.fitted = True
        return self

    def calibrate(self, confidence: float, is_ood: bool = False) -> float:
        # Safety invariant: OOD input capped
        if is_ood:
            return min(0.35, confidence * 0.40)

        if not self.breakpoints:
            return confidence

        # Piecewise constant lookup
        if confidence <= self.breakpoints[0][0]:
            return self.breakpoints[0][1]
        for i in range(len(self.breakpoints) - 1):
            x1, y1 = self.breakpoints[i]
            x2, y2 = self.breakpoints[i + 1]
            if x1 <= confidence <= x2:
                # Linear interpolation between adjacent breakpoints
                t = (confidence - x1) / (x2 - x1) if x2 > x1 else 0.0
                return round(y1 + t * (y2 - y1), 4)
        return self.breakpoints[-1][1]


class ModelCalibrationManager:
    """Manages versioned calibrator artifacts, stratification by class/device/zone, and drift intervals."""

    def __init__(self, artifacts_dir: Optional[Path] = None):
        self.artifacts_dir = artifacts_dir or Path("src/config/calibrators")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.calibrators: Dict[str, TemperatureScalingCalibrator] = {}

    def get_or_fit_calibrator(
        self,
        model_version: str,
        confidences: List[float],
        labels: List[int],
    ) -> TemperatureScalingCalibrator:
        if model_version in self.calibrators:
            return self.calibrators[model_version]

        calibrator = TemperatureScalingCalibrator(model_version=model_version)
        calibrator.fit(confidences, labels)
        self.calibrators[model_version] = calibrator
        self.save_calibrator(calibrator)
        return calibrator

    def save_calibrator(self, calibrator: TemperatureScalingCalibrator) -> Path:
        p = self.artifacts_dir / f"calibrator_{calibrator.model_version}.json"
        data = {
            "model_version": calibrator.model_version,
            "temperature": calibrator.temperature,
            "fitted": calibrator.fitted,
        }
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return p

    def evaluate_stratified_slices(
        self,
        samples: List[Dict[str, Any]],  # conf, label, pred, class, device, zone, period (pre/post drift)
    ) -> Dict[str, Any]:
        """
        Evaluates ECE, Brier score, and calibration quality across:
        - overall
        - per-class
        - by-device
        - by-zone
        - pre-drift vs post-drift
        """
        def get_metrics_for_sublist(sub: List[Dict[str, Any]]) -> Dict[str, Any]:
            c = [s["conf"] for s in sub]
            y = [1 if s["pred"] == s["label"] else 0 for s in sub]
            return compute_calibration_metrics(c, y).to_dict()

        overall = get_metrics_for_sublist(samples)

        # 1. Per class
        by_class: Dict[str, Any] = {}
        for cls_name in ["NORMAL", "ACCIDENT", "FIRE", "AMBULANCE"]:
            sub = [s for s in samples if s.get("class") == cls_name]
            if sub:
                by_class[cls_name] = get_metrics_for_sublist(sub)

        # 2. By device
        by_device: Dict[str, Any] = {}
        for dev in ["camera", "audio", "sensors"]:
            sub = [s for s in samples if s.get("device") == dev]
            if sub:
                by_device[dev] = get_metrics_for_sublist(sub)

        # 3. By zone
        by_zone: Dict[str, Any] = {}
        for z in ["ZONE_A_INTERSECTION", "ZONE_B_INTERSECTION", "ZONE_C_CORRIDOR"]:
            sub = [s for s in samples if s.get("zone") == z]
            if sub:
                by_zone[z] = get_metrics_for_sublist(sub)

        # 4. Drift period
        by_drift: Dict[str, Any] = {}
        for period in ["PRE_DRIFT", "POST_DRIFT"]:
            sub = [s for s in samples if s.get("drift_period") == period]
            if sub:
                by_drift[period] = get_metrics_for_sublist(sub)

        return {
            "overall": overall,
            "by_class": by_class,
            "by_device": by_device,
            "by_zone": by_zone,
            "by_drift_period": by_drift,
        }
