"""
Test Suite: Phase 6 Item 2 - Edge OOD and Drift Monitoring Refinements.
====================================================================
Tests the RefinedEdgeDriftMonitor implementing dual-scale fast/slow windows,
exponential moving average (EMA) PSI smoothing, and automated assurance
level degradation recommendations.
"""
from __future__ import annotations

import pytest
from src.modules.assurance.refined_drift_monitor import RefinedEdgeDriftMonitor


def test_stationary_baseline_no_false_drift():
    """
    Hypothesis: On a stationary distribution matching baseline, the refined monitor
    suppresses false drift alarms, reporting STABLE status and FULL assurance.
    """
    # 5 bins: equal distribution
    baseline = [20, 20, 20, 20, 20]
    monitor = RefinedEdgeDriftMonitor(
        model_id="yolo_v8_tiny",
        baseline_histogram=baseline,
        fast_window_size=20,
        slow_window_size=100,
        ema_alpha=0.25,
    )

    # Ingest 100 samples matching the uniform distribution across [0.0, 1.0]
    for i in range(100):
        conf = (i % 5) * 0.2 + 0.1  # 0.1, 0.3, 0.5, 0.7, 0.9
        monitor.ingest_prediction(confidence=conf, is_ood=False)

    result = monitor.evaluate_drift()

    assert result.status == "STABLE"
    assert result.recommended_assurance == "FULL"
    assert result.psi_instantaneous < 0.10
    assert result.psi_ema < 0.10
    assert result.ood_rate == 0.0
    assert "INSUFFICIENT_SAMPLES" not in result.reasons


def test_sudden_distribution_shock_fast_detection():
    """
    Hypothesis: Sudden distribution collapse (e.g., lens occlusion dropping confidence to 0.05)
    is caught within 20 samples by the agile fast-window without needing 100 samples.
    """
    # Baseline expects high confidence (concentrated in bins 4 and 5)
    baseline = [5, 5, 10, 40, 40]
    monitor = RefinedEdgeDriftMonitor(
        model_id="yolo_v8_tiny",
        baseline_histogram=baseline,
        fast_window_size=20,
        slow_window_size=100,
        ema_alpha=0.3,
    )

    # First initialize with 20 normal samples
    for _ in range(20):
        monitor.ingest_prediction(confidence=0.85, is_ood=False)

    # Now inject severe shock (low confidence + OOD) for 20 frames
    for _ in range(20):
        monitor.ingest_prediction(confidence=0.08, is_ood=True)

    result = monitor.evaluate_drift()

    assert result.status == "DRIFT_DETECTED"
    assert result.recommended_assurance == "DEGRADED"
    assert result.fast_window_samples == 20
    assert result.ood_rate >= 0.50
    assert any("HIGH_PSI_DRIFT" in r or "ELEVATED_OOD_RATE" in r for r in result.reasons)


def test_gradual_drift_ema_smoothing_and_watch_state():
    """
    Hypothesis: Moderate drift creates a smooth transition into WATCH state
    and recommends REVIEW_REQUIRED before escalating to DEGRADED.
    """
    baseline = [10, 20, 40, 20, 10]
    monitor = RefinedEdgeDriftMonitor(
        model_id="audio_yamnet_edge",
        baseline_histogram=baseline,
        fast_window_size=20,
        slow_window_size=100,
        psi_watch=0.10,
        psi_drift=0.30,
        ema_alpha=0.20,
    )

    # Ingest moderately shifted predictions
    for _ in range(50):
        monitor.ingest_prediction(confidence=0.35, is_ood=False)

    result = monitor.evaluate_drift()

    assert result.status in ("WATCH", "DRIFT_DETECTED")
    assert result.recommended_assurance in ("REVIEW_REQUIRED", "DEGRADED")
    data_dict = result.to_dict()
    assert "psi_ema" in data_dict
    assert "recommended_assurance" in data_dict
