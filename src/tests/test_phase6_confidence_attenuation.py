"""
Test Suite: Phase 6 Item 4 - Confidence Reduction on Sensor Failure.
===================================================================
Tests dynamic confidence discounting and risk ceiling enforcement when
sensor inputs are degraded, dropping packets, or disconnected.
"""
from __future__ import annotations

import pytest
from src.modules.sensor_fusion.confidence_attenuation import (
    SensorConfidenceAttenuator,
    SensorHealthState,
)


def test_healthy_sensor_full_confidence_and_risk():
    """
    Hypothesis: When sensors are HEALTHY with 0% drop rate, confidence and risk
    pass through without attenuation or ceiling capping.
    """
    attenuator = SensorConfidenceAttenuator()
    sensors = [
        SensorHealthState(sensor_id="cam_01", modality="CAMERA", status="HEALTHY", drop_rate=0.0),
        SensorHealthState(sensor_id="mic_01", modality="AUDIO", status="HEALTHY", drop_rate=0.0),
    ]

    res = attenuator.evaluate_event(
        primary_modality="CAMERA",
        raw_confidence=0.90,
        raw_risk_score=0.85,
        sensor_states=sensors,
    )

    assert res.effective_sensor_weight == 1.0
    assert pytest.approx(res.attenuated_confidence, 0.001) == 0.90
    assert pytest.approx(res.attenuated_risk_score, 0.001) == 0.85
    assert res.risk_cap_applied is False
    assert len(res.reasons) == 0


def test_degraded_sensor_attenuates_confidence_and_caps_risk():
    """
    Hypothesis: When primary camera is DEGRADED, confidence is discounted by 50%
    and risk score is bounded below the critical escalation threshold (<= 0.45).
    """
    attenuator = SensorConfidenceAttenuator()
    sensors = [
        SensorHealthState(sensor_id="cam_01", modality="CAMERA", status="DEGRADED", drop_rate=0.0),
    ]

    res = attenuator.evaluate_event(
        primary_modality="CAMERA",
        raw_confidence=0.95,
        raw_risk_score=0.92,
        sensor_states=sensors,
    )

    # Base weight 0.5 -> confidence becomes 0.95 * 0.5 = 0.475
    assert pytest.approx(res.attenuated_confidence, 0.001) == 0.475
    # Risk would be 0.92 * 0.5 = 0.46, capped at 0.45
    assert res.attenuated_risk_score <= 0.45
    assert res.risk_cap_applied is True
    assert any("PRIMARY_SENSOR_DEGRADED" in r for r in res.reasons)
    assert any("RISK_CEILING_ENFORCED" in r for r in res.reasons)


def test_sensor_down_drops_confidence_to_zero():
    """
    Hypothesis: When primary sensor is DOWN, weight drops to 0.0,
    suppressing all confidence and enforcing DOWN risk cap.
    """
    attenuator = SensorConfidenceAttenuator()
    sensors = [
        SensorHealthState(sensor_id="mic_01", modality="AUDIO", status="DOWN", drop_rate=1.0),
    ]

    res = attenuator.evaluate_event(
        primary_modality="AUDIO",
        raw_confidence=0.99,
        raw_risk_score=0.95,
        sensor_states=sensors,
    )

    assert res.effective_sensor_weight == 0.0
    assert res.attenuated_confidence == 0.0
    assert res.attenuated_risk_score == 0.0
    assert any("PRIMARY_SENSOR_DOWN" in r for r in res.reasons)
