"""Unit and property-based invariance tests for Phase 6B Uncertainty-Aware Fusion."""
from __future__ import annotations

import pytest
from src.modules.decision.uncertainty_fusion import (
    RiskFactors,
    UncertaintyAwareFusion,
    UncertaintyDecision,
)


def test_risk_factor_bounds_and_computation():
    """Verify all factors are strictly bounded in [0.0, 1.0] and product matches specification."""
    factors = RiskFactors(
        event_confidence=0.90,
        temporal_consistency=0.80,
        sensor_agreement=0.85,
        device_health=0.95,
        calibration_quality=1.0,
        ood_penalty=1.0,
        evidence_duration_penalty=1.0,
        zone_reliability_penalty=1.0,
    )
    # Expected: 0.90 * 0.80 * 0.85 * 0.95 * 1.0 = 0.5814
    risk = factors.compute_final_risk()
    assert risk == pytest.approx(0.5814, 0.001)
    assert 0.0 <= risk <= 1.0


def test_monotonic_non_increasing_invariance_property():
    """
    Property-based test: Degrading ANY sensor or health input can NEVER increase final_risk.
    """
    engine = UncertaintyAwareFusion()

    base_health = {"camera": 1.0, "audio": 1.0, "sensors": 1.0}
    base_sensors = {"camera": "FIRE", "audio": "FIRE", "sensors": "FIRE"}
    base_history = ["FIRE"] * 5

    base_dec = engine.evaluate(
        predicted_class="FIRE",
        raw_confidence=0.95,
        window_history=base_history,
        active_sensor_classes=base_sensors,
        device_health_inputs=base_health,
        is_ood=False,
    )

    # 1. Degrade camera health (1.0 -> 0.0)
    degraded_health_dec = engine.evaluate(
        predicted_class="FIRE",
        raw_confidence=0.95,
        window_history=base_history,
        active_sensor_classes=base_sensors,
        device_health_inputs={"camera": 0.0, "audio": 1.0, "sensors": 1.0},
        is_ood=False,
    )
    assert degraded_health_dec.final_risk <= base_dec.final_risk, "Degrading camera health increased risk!"

    # 2. Introduce sensor disagreement (audio changes to NORMAL)
    disagree_sensors = {"camera": "FIRE", "audio": "NORMAL", "sensors": "FIRE"}
    disagree_dec = engine.evaluate(
        predicted_class="FIRE",
        raw_confidence=0.95,
        window_history=base_history,
        active_sensor_classes=disagree_sensors,
        device_health_inputs=base_health,
        is_ood=False,
    )
    assert disagree_dec.final_risk <= base_dec.final_risk, "Sensor disagreement increased risk!"

    # 3. Introduce OOD anomaly
    ood_dec = engine.evaluate(
        predicted_class="FIRE",
        raw_confidence=0.95,
        window_history=base_history,
        active_sensor_classes=base_sensors,
        device_health_inputs=base_health,
        is_ood=True,
    )
    assert ood_dec.final_risk <= base_dec.final_risk, "OOD anomaly increased risk!"

    # 4. Short evidence duration
    short_dec = engine.evaluate(
        predicted_class="FIRE",
        raw_confidence=0.95,
        window_history=base_history,
        active_sensor_classes=base_sensors,
        device_health_inputs=base_health,
        evidence_duration_sec=0.4,
    )
    assert short_dec.final_risk <= base_dec.final_risk, "Short evidence duration increased risk!"


def test_safety_guard_routes_to_review_required():
    """
    Safety Guard: When risk drops below alert threshold (0.50) but raw evidence is strong (>= 0.65),
    event must be routed to REVIEW_REQUIRED rather than silently dropped as SUPPRESS_NOISE.
    """
    engine = UncertaintyAwareFusion(alert_threshold=0.50, strong_evidence_threshold=0.65)

    # High raw confidence (0.85) but degraded audio/camera health pulls final risk below 0.50
    health_degraded = {"camera": 0.3, "audio": 0.2, "sensors": 0.8}
    dec = engine.evaluate(
        predicted_class="ACCIDENT",
        raw_confidence=0.85,
        window_history=["ACCIDENT", "NORMAL"],
        active_sensor_classes={"camera": "ACCIDENT", "audio": "NORMAL", "sensors": "NORMAL"},
        device_health_inputs=health_degraded,
    )

    assert dec.final_risk < 0.50
    assert dec.action == "REVIEW_REQUIRED", f"Expected REVIEW_REQUIRED, got {dec.action}"
    assert "Safety guard triggered" in dec.reason


def test_configurable_factor_ablations():
    """Verify that removing one factor at a time (ablations) properly isolates factor impact."""
    factors = RiskFactors(
        event_confidence=0.90,
        temporal_consistency=0.70,
        sensor_agreement=0.60,
        device_health=0.80,
        calibration_quality=1.0,
    )

    # Full risk
    risk_full = factors.compute_final_risk()

    # Ablate temporal consistency (ignore temporal)
    risk_no_temp = factors.compute_final_risk(enabled_factors={"sensor_agreement", "device_health", "calibration_quality"})
    assert risk_no_temp == pytest.approx(0.90 * 0.60 * 0.80, 0.001)
    assert risk_no_temp > risk_full

    # Ablate sensor agreement
    risk_no_agree = factors.compute_final_risk(enabled_factors={"temporal_consistency", "device_health", "calibration_quality"})
    assert risk_no_agree == pytest.approx(0.90 * 0.70 * 0.80, 0.001)
    assert risk_no_agree > risk_full


def test_full_decision_factor_persistence():
    """Verify every factor is persisted in the decision dictionary for audit reporting."""
    engine = UncertaintyAwareFusion()
    dec = engine.evaluate(
        predicted_class="FIRE",
        raw_confidence=0.88,
        window_history=["FIRE", "FIRE"],
        active_sensor_classes={"camera": "FIRE", "audio": "FIRE"},
        device_health_inputs={"camera": 1.0, "audio": 1.0},
    )

    d = dec.to_dict()
    assert "factors" in d
    assert "event_confidence" in d["factors"]
    assert "temporal_consistency" in d["factors"]
    assert "sensor_agreement" in d["factors"]
    assert "device_health" in d["factors"]
    assert "calibration_quality" in d["factors"]
    assert "action" in d
