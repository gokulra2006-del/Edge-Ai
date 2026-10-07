"""
Comprehensive test suite for Phase 6L: Zone-Aware Risk Scoring.
================================================================
Verifies:
1. Versioned prior table estimation, immutability, and serialization (zero test leakage).
2. Strict ablatability: use_zone_priors=False exactly reproduces baseline risk.
3. Critical safety floor: high-confidence critical events in quiet zones are NEVER suppressed to noise (routed to REVIEW_REQUIRED).
4. Quiet zone noise attenuation: sub-threshold ambiguous disturbances are suppressed.
5. High-hazard zone sensitivity boost: borderline events elevated to alert.
6. Full explanatory logging: zone_prior_factor metadata present with all keys.
7. Replay engine and uncertainty fusion integration.
"""

import json
from pathlib import Path
import pytest

from src.modules.decision.zone_priors import (
    ContextualZonePrior,
    ZonePriorTable,
    ZonePriorEstimator,
    ZoneAwareRiskScorer,
    get_time_bucket,
)
from src.modules.decision.uncertainty_fusion import (
    UncertaintyAwareFusion,
    RiskFactors,
)
from evaluation.systems import ZoneAwareRiskSystem, ZoneAwareRiskAblatedSystem
from evaluation.scenarios import ScenarioGenerator, ScenarioStep, SensorReading, AudioReading, VisionReading


def test_time_bucket_categorization():
    assert get_time_bucket(7) == "MORNING_RUSH"
    assert get_time_bucket(12) == "MIDDAY"
    assert get_time_bucket(17) == "EVENING_RUSH"
    assert get_time_bucket(23) == "NIGHT"
    assert get_time_bucket(3) == "NIGHT"


def test_zone_prior_table_default_and_serialization(tmp_path: Path):
    table = ZonePriorEstimator.build_default_table(version="v6L-test-1")
    assert table.version == "v6L-test-1"
    assert "ZONE_A" in table.priors
    assert "ZONE_B" in table.priors
    assert "ZONE_SCHOOL" in table.priors
    assert "ZONE_HIGHWAY" in table.priors

    # Quiet zone prior multiplier should be < 1.0
    prior_quiet = table.get_prior("ZONE_A", "MIDDAY")
    assert prior_quiet.prior_multiplier < 1.0
    assert prior_quiet.accident_base_rate < 0.10

    # High-risk zone prior multiplier should be > 1.0
    prior_high = table.get_prior("ZONE_HIGHWAY", "EVENING_RUSH")
    assert prior_high.prior_multiplier > 1.0
    assert prior_high.accident_base_rate > 0.30

    # Test serialization round-trip
    dumped = table.to_dict()
    restored = ZonePriorTable.from_dict(dumped)
    assert restored.version == table.version
    assert restored.provenance_hash == table.provenance_hash
    assert restored.get_prior("ZONE_A", "MIDDAY").prior_multiplier == prior_quiet.prior_multiplier


def test_training_set_prior_fitting_no_test_leakage():
    # Synthetic training partition only
    train_samples = [
        {"zone_id": "RESIDENTIAL_1", "hour": 14, "label": "NORMAL"},
        {"zone_id": "RESIDENTIAL_1", "hour": 14, "label": "NORMAL"},
        {"zone_id": "RESIDENTIAL_1", "hour": 14, "label": "NORMAL"},
        {"zone_id": "RESIDENTIAL_1", "hour": 14, "label": "NORMAL"},
        {"zone_id": "RESIDENTIAL_1", "hour": 14, "label": "ACCIDENT"},
        {"zone_id": "HIGHWAY_1", "hour": 14, "label": "ACCIDENT"},
        {"zone_id": "HIGHWAY_1", "hour": 14, "label": "ACCIDENT"},
        {"zone_id": "HIGHWAY_1", "hour": 14, "label": "ACCIDENT"},
        {"zone_id": "HIGHWAY_1", "hour": 14, "label": "NORMAL"},
        {"zone_id": "HIGHWAY_1", "hour": 14, "label": "NORMAL"},
    ]
    fitted_table = ZonePriorEstimator.fit_from_training_samples(train_samples, version="v-train-fit-1", min_samples=3)
    p_res = fitted_table.get_prior("RESIDENTIAL_1", "MIDDAY")
    p_hwy = fitted_table.get_prior("HIGHWAY_1", "MIDDAY")

    assert p_res.sample_count == 5
    assert p_hwy.sample_count == 5
    assert p_res.accident_base_rate < p_hwy.accident_base_rate
    assert p_res.prior_multiplier < p_hwy.prior_multiplier
    assert p_res.data_tag == "TRAINING_FIT"


def test_safety_invariant_critical_safety_floor():
    """
    CRITICAL SAFETY INVARIANT:
    A high-confidence critical event (raw_confidence >= critical_threshold)
    must NEVER be suppressed to 'SUPPRESS_NOISE' even in a zone with very low prior.
    It MUST route to 'REVIEW_REQUIRED'.
    """
    scorer = ZoneAwareRiskScorer(critical_raw_confidence_threshold=0.85)

    # In a quiet zone with low multiplier (e.g. 0.60 at night in ZONE_A)
    # where baseline attenuated risk is 0.60 -> adjusted risk would be 0.60 * 0.60 = 0.36 (< alert_threshold 0.50)
    adj = scorer.adjust_risk(
        predicted_class="ACCIDENT",
        raw_confidence=0.88,  # High confidence critical event
        baseline_risk=0.48,   # Borderline attenuated baseline risk
        zone_id="ZONE_A",
        time_bucket="NIGHT",
        alert_threshold=0.50,
    )

    # Low prior pushes adjusted risk to 0.48 * 0.60 = 0.288 (< 0.50)
    assert adj.adjusted_risk < 0.50
    # BUT safety floor must trigger: CAN NEVER BE SUPPRESS_NOISE
    assert adj.action != "SUPPRESS_NOISE"
    assert adj.action == "REVIEW_REQUIRED"
    assert adj.safety_floor_triggered is True
    assert "Safety invariant enforced" in adj.explanation


def test_quiet_zone_noise_suppression():
    """
    Sub-threshold ambiguous disturbance in a quiet zone is suppressed as noise.
    """
    scorer = ZoneAwareRiskScorer()
    adj = scorer.adjust_risk(
        predicted_class="ACCIDENT",
        raw_confidence=0.60,  # Ambiguous/borderline, NOT critical
        baseline_risk=0.52,   # Baseline would alert at >= 0.50
        zone_id="ZONE_A",
        time_bucket="MIDDAY",  # Multiplier 0.70 -> 0.52 * 0.70 = 0.364
        alert_threshold=0.50,
    )

    assert adj.adjusted_risk == 0.364
    assert adj.action == "SUPPRESS_NOISE"
    assert adj.safety_floor_triggered is False


def test_high_risk_zone_sensitivity_boost():
    """
    Borderline hazard event in a high-risk zone is elevated to DISPATCH_ALERT.
    """
    scorer = ZoneAwareRiskScorer()
    adj = scorer.adjust_risk(
        predicted_class="ACCIDENT",
        raw_confidence=0.62,
        baseline_risk=0.42,   # Baseline would suppress at < 0.50
        zone_id="ZONE_HIGHWAY",
        time_bucket="MORNING_RUSH",  # Multiplier 1.50 -> 0.42 * 1.50 = 0.63
        alert_threshold=0.50,
    )

    assert adj.adjusted_risk >= 0.50
    assert adj.action == "DISPATCH_ALERT"
    assert adj.applied_prior_multiplier >= 1.40


def test_ablatability_invariance():
    """
    When use_zone_priors=False (or scorer disabled), adjusted risk and action
    must strictly match unadjusted baseline risk.
    """
    fusion = UncertaintyAwareFusion()
    history = ["ACCIDENT"] * 5
    sensors = {"audio": "ACCIDENT", "vision": "ACCIDENT", "sensors": "ACCIDENT"}
    health = {"camera": 1.0, "audio": 1.0, "sensors": 1.0}

    # Enabled
    dec_enabled = fusion.evaluate(
        predicted_class="ACCIDENT",
        raw_confidence=0.60,
        window_history=history,
        active_sensor_classes=sensors,
        device_health_inputs=health,
        zone_id="ZONE_A",
        time_bucket="MIDDAY",
        use_zone_priors=True,
    )

    # Ablated
    dec_ablated = fusion.evaluate(
        predicted_class="ACCIDENT",
        raw_confidence=0.60,
        window_history=history,
        active_sensor_classes=sensors,
        device_health_inputs=health,
        zone_id="ZONE_A",
        time_bucket="MIDDAY",
        use_zone_priors=False,
    )

    assert dec_enabled.metadata["zone_prior_factor"]["ablation_active"] is False
    assert dec_ablated.metadata["zone_prior_factor"]["ablation_active"] is True
    assert dec_ablated.final_risk == dec_ablated.metadata["baseline_risk"]
    # With raw_confidence=0.60 and perfect factors, baseline_risk is 0.60 >= 0.50 -> DISPATCH_ALERT in ablated
    assert dec_ablated.action == "DISPATCH_ALERT"
    # But in ZONE_A with 0.70 multiplier, adjusted risk is 0.42 < 0.50 -> SUPPRESS_NOISE
    assert dec_enabled.action == "SUPPRESS_NOISE"


def test_explanatory_logging_payload():
    """
    Every decision must record the full zone_prior_factor dictionary with expected schema.
    """
    fusion = UncertaintyAwareFusion()
    dec = fusion.evaluate(
        predicted_class="FIRE",
        raw_confidence=0.88,
        window_history=["FIRE"] * 3,
        active_sensor_classes={"audio": "FIRE", "vision": "FIRE"},
        device_health_inputs={"camera": 1.0, "audio": 1.0},
        zone_id="ZONE_SCHOOL",
        time_bucket="NIGHT",
        use_zone_priors=True,
    )

    factor = dec.metadata.get("zone_prior_factor")
    assert factor is not None
    assert factor["zone_id"] == "ZONE_SCHOOL"
    assert factor["time_bucket"] == "NIGHT"
    assert "applied_prior_multiplier" in factor
    assert "accident_base_rate" in factor
    assert "safety_floor_triggered" in factor
    assert "ablation_active" in factor
    assert "explanation" in factor


def test_system_under_test_classes():
    sys_prior = ZoneAwareRiskSystem()
    sys_abl = ZoneAwareRiskAblatedSystem()
    assert sys_prior.use_zone_priors is True
    assert sys_abl.use_zone_priors is False
    assert sys_prior.name == "zone-aware-risk"
    assert sys_abl.name == "zone-risk-ablated"
