"""
Test Suite: Phase 6 Item 10 - Reproducible Incident Replay for Evaluation.
========================================================================
Validates virtual-time deterministic incident replay, identical cross-run
risk trajectories, and counterfactual threshold sensitivity.
"""
from __future__ import annotations

import json
import pytest
from src.modules.incident_management.incident_replay import (
    IncidentReplayEngine,
    ReplayTelemetryEvent,
)

SAMPLE_TRACE = json.dumps([
    {"timestamp_offset_ms": 0, "modality": "CAMERA", "event_type": "RAPID_APPROACH", "confidence": 0.50},
    {"timestamp_offset_ms": 250, "modality": "AUDIO", "event_type": "TIRE_SCREECH", "confidence": 0.82},
    {"timestamp_offset_ms": 500, "modality": "CAMERA", "event_type": "VEHICLE_COLLISION", "confidence": 0.94},
])


def test_incident_replay_determinism():
    """
    Hypothesis: Repeated execution of the same telemetry trace yields bit-exact
    identical risk trajectories and declaration steps across repeated runs.
    """
    engine1 = IncidentReplayEngine(incident_id="INC-REPLAY-1", declaration_threshold=0.75)
    engine1.load_telemetry_trace(SAMPLE_TRACE)
    logs1, sum1 = engine1.run_replay()

    engine2 = IncidentReplayEngine(incident_id="INC-REPLAY-1", declaration_threshold=0.75)
    engine2.load_telemetry_trace(SAMPLE_TRACE)
    logs2, sum2 = engine2.run_replay()

    # 1. Summary comparison
    assert sum1 == sum2
    assert sum1["incident_declared"] is True
    assert sum1["declaration_step"] == 2  # Declared on step 2 (VEHICLE_COLLISION)

    # 2. Step-by-step risk trajectory match
    assert len(logs1) == len(logs2) == 3
    for s1, s2 in zip(logs1, logs2):
        assert s1.step_index == s2.step_index
        assert s1.accumulated_risk == s2.accumulated_risk
        assert s1.engine_state == s2.engine_state


def test_counterfactual_threshold_tuning():
    """
    Hypothesis: Raising the declaration threshold changes the declaration step
    deterministically for counterfactual hypothesis testing.
    """
    # Baseline threshold 0.75 declares at step 2
    engine_low = IncidentReplayEngine(incident_id="INC-CF-1", declaration_threshold=0.75)
    engine_low.load_telemetry_trace(SAMPLE_TRACE)
    _, sum_low = engine_low.run_replay()
    assert sum_low["incident_declared"] is True

    # Ultra-high threshold 0.99 never declares incident
    engine_high = IncidentReplayEngine(incident_id="INC-CF-1", declaration_threshold=0.99)
    engine_high.load_telemetry_trace(SAMPLE_TRACE)
    _, sum_high = engine_high.run_replay()
    assert sum_high["incident_declared"] is False
    assert sum_high["declaration_step"] is None
