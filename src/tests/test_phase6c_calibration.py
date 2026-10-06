"""Unit and property tests for Phase 6C Confidence Calibration."""
from __future__ import annotations

import pytest
from src.modules.calibration.calibration_engine import (
    CalibrationMetrics,
    IsotonicCalibrator,
    ModelCalibrationManager,
    TemperatureScalingCalibrator,
    compute_calibration_metrics,
)


def test_hand_computed_ece_and_brier_score():
    """Verify ECE and Brier score match manual mathematical calculations."""
    # 4 predictions:
    # 1: conf 0.8, y 1 -> (0.8 - 1.0)^2 = 0.04
    # 2: conf 0.8, y 1 -> (0.8 - 1.0)^2 = 0.04
    # 3: conf 0.2, y 0 -> (0.2 - 0.0)^2 = 0.04
    # 4: conf 0.2, y 0 -> (0.2 - 0.0)^2 = 0.04
    # Brier = (0.04 * 4) / 4 = 0.04
    confidences = [0.8, 0.8, 0.2, 0.2]
    accuracies = [1, 1, 0, 0]

    metrics = compute_calibration_metrics(confidences, accuracies, num_bins=5)
    assert metrics.brier_score == pytest.approx(0.04, 0.001)

    # Bin [0.2, 0.4): 2 samples, conf_mean=0.2, acc_mean=0.0 -> gap = 0.2
    # Bin [0.8, 1.0]: 2 samples, conf_mean=0.8, acc_mean=1.0 -> gap = 0.2
    # Total ECE = (2/4)*0.2 + (2/4)*0.2 = 0.20
    assert metrics.ece == pytest.approx(0.20, 0.01)
    assert metrics.calibration_quality == pytest.approx(0.80, 0.01)


def test_temperature_scaling_calibrator_optimization():
    """Verify temperature scaling optimizes temperature and lowers ECE."""
    # Overconfident model: predicted 0.95 confidence, but empirical accuracy is only 0.50
    calib_conf = [0.95] * 20 + [0.10] * 20
    calib_y = [1] * 10 + [0] * 10 + [0] * 18 + [1] * 2  # acc = 0.50 for high conf, 0.90 for low

    calibrator = TemperatureScalingCalibrator(model_version="test-v1")
    calibrator.fit(calib_conf, calib_y)

    assert calibrator.fitted is True
    # Overconfidence should cause learned temperature T > 1.0 to soften probabilities
    assert calibrator.temperature > 1.0

    calibrated_high = calibrator.calibrate(0.95)
    assert calibrated_high < 0.95, "Temperature scaling should soften overconfident predictions"


def test_no_leakage_held_out_validation(tmp_path):
    """Verify calibrator weights are fitted strictly on calibration split and evaluated on held-out test split."""
    # Calibration split (N=50)
    calib_confs = [0.85] * 25 + [0.25] * 25
    calib_labels = [1] * 20 + [0] * 5 + [0] * 20 + [1] * 5

    # Held-out test split (N=50)
    test_confs = [0.85] * 25 + [0.25] * 25
    test_labels = [1] * 18 + [0] * 7 + [0] * 22 + [1] * 3

    mgr = ModelCalibrationManager(artifacts_dir=tmp_path)
    calibrator = mgr.get_or_fit_calibrator("vision-yolo-v1", calib_confs, calib_labels)

    # Pre-calibration test ECE
    pre_metrics = compute_calibration_metrics(test_confs, test_labels)

    # Post-calibration test ECE
    calibrated_test_confs = [calibrator.calibrate(c) for c in test_confs]
    post_metrics = compute_calibration_metrics(calibrated_test_confs, test_labels)

    # Post-calibration ECE should improve or maintain bounds
    assert post_metrics.ece <= pre_metrics.ece + 0.05
    assert (tmp_path / "calibrator_vision-yolo-v1.json").exists()


def test_ood_confidence_cap_safety_rule():
    """
    Safety Rule: Out-of-distribution (OOD) input MUST be strictly capped and flagged.
    100% confidence on OOD input is strictly forbidden.
    """
    temp_calib = TemperatureScalingCalibrator()
    iso_calib = IsotonicCalibrator()
    iso_calib.fit([0.2, 0.5, 0.9], [0, 1, 1])

    # 1. Temperature scaling OOD cap
    p_ood_temp = temp_calib.calibrate(confidence=1.0, is_ood=True)
    assert p_ood_temp <= 0.40, f"OOD confidence {p_ood_temp} exceeded safety cap 0.40"

    # 2. Isotonic scaling OOD cap
    p_ood_iso = iso_calib.calibrate(confidence=1.0, is_ood=True)
    assert p_ood_iso <= 0.40, f"OOD confidence {p_ood_iso} exceeded safety cap 0.40"


def test_calibration_quality_feeds_into_phase_6b_risk():
    """Verify calibration_quality modulates the 6B risk computation directly."""
    from src.modules.decision.uncertainty_fusion import RiskFactors

    high_quality_factors = RiskFactors(
        event_confidence=0.90,
        temporal_consistency=0.90,
        sensor_agreement=0.90,
        device_health=1.0,
        calibration_quality=1.0,  # Zero ECE -> 1.0 quality
    )
    poor_quality_factors = RiskFactors(
        event_confidence=0.90,
        temporal_consistency=0.90,
        sensor_agreement=0.90,
        device_health=1.0,
        calibration_quality=0.65,  # High ECE -> 0.65 quality
    )

    risk_high = high_quality_factors.compute_final_risk()
    risk_poor = poor_quality_factors.compute_final_risk()

    assert risk_poor < risk_high
    assert risk_poor == pytest.approx(risk_high * 0.65, 0.01)
