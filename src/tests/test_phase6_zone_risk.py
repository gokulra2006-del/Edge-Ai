"""
Test Suite: Phase 6 Item 7 - Zone-Aware Risk Scoring.
===================================================
Tests dynamic spatial risk adjustments, vulnerability tiers, and crowd density
scaling across diverse environmental zones.
"""
from __future__ import annotations

import pytest
from src.modules.decision_engine.zone_risk import ZoneAwareRiskEngine


def test_zone_risk_differentiation():
    """
    Hypothesis: The same detection event produces significantly higher calibrated risk
    in a school zone than in an industrial storage yard.
    """
    engine = ZoneAwareRiskEngine()

    school_res = engine.assess_risk(
        zone_id="ZONE_SCHOOL",
        raw_confidence=0.80,
        event_severity="HIGH",
        crowd_density=0,
    )

    ind_res = engine.assess_risk(
        zone_id="ZONE_INDUSTRIAL",
        raw_confidence=0.80,
        event_severity="HIGH",
        crowd_density=0,
    )

    # Base risk is identical for both (0.80 * 0.85 = 0.68)
    assert school_res.base_risk == ind_res.base_risk
    # But calibrated risk in school zone is amplified by 1.40x vs 0.75x in industrial
    assert school_res.calibrated_risk > ind_res.calibrated_risk
    assert school_res.calibrated_risk > 0.90
    assert ind_res.calibrated_risk < 0.55


def test_crowd_density_monotonic_scaling():
    """
    Hypothesis: As pedestrian crowd density increases in a commercial zone,
    calibrated risk monotonically increases up to the defined cap.
    """
    engine = ZoneAwareRiskEngine()

    res_empty = engine.assess_risk("ZONE_COMMERCIAL", raw_confidence=0.70, crowd_density=0)
    res_medium = engine.assess_risk("ZONE_COMMERCIAL", raw_confidence=0.70, crowd_density=5)
    res_crowded = engine.assess_risk("ZONE_COMMERCIAL", raw_confidence=0.70, crowd_density=20)

    assert res_empty.calibrated_risk < res_medium.calibrated_risk
    assert res_medium.calibrated_risk < res_crowded.calibrated_risk
    assert any("CROWD_DENSITY_BOOST" in r for r in res_crowded.reasons)
