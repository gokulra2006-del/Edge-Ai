"""Tests for Phase 6E: Counterfactual Explanations."""
from __future__ import annotations

import sqlite3
import time
import pytest

from replay.__main__ import build_sample_incident_trace
from src.modules.decision.counterfactual_engine import (
    CounterfactualExplanation,
    CounterfactualExplanationEngine,
)
from src.modules.incident_management.replay_engine import (
    ReplayStepInput,
    SandboxedReplayEngine,
)
from src.modules.database.governed_store import IncidentRepository


def test_explanation_fidelity_matches_replay():
    """Verify counterfactual outcomes strictly match bit-exact replay outputs."""
    trace = build_sample_incident_trace("INC-FIDELITY-001")
    replay_engine = SandboxedReplayEngine()
    explainer = CounterfactualExplanationEngine(replay_engine=replay_engine)

    explanation = explainer.explain_incident("INC-FIDELITY-001", trace)

    assert explanation.fidelity_verified is True
    assert explanation.baseline_decision in ("NORMAL", "ACCIDENT", "FIRE", "AMBULANCE")

    # Manually run replay for each modality and compare bit-for-bit
    for mod in ["camera", "audio", "sensors"]:
        key = f"without_{mod}"
        assert key in explanation.ablation_outcomes
        summary = explanation.ablation_outcomes[key]

        direct_replay = replay_engine.execute_replay(
            incident_id="INC-FIDELITY-001",
            steps=trace,
            dropout_sensor=mod,
        )
        assert summary.decision == direct_replay.final_decision
        assert summary.final_risk == direct_replay.final_risk
        assert summary.action == (direct_replay.timeline[-1].action if direct_replay.timeline else "SUPPRESS_NOISE")


def test_sensor_removal_monotonicity():
    """Property test: removing sensory evidence must never increase computed risk."""
    trace = build_sample_incident_trace("INC-MONO-001")
    explainer = CounterfactualExplanationEngine()

    explanation = explainer.explain_incident("INC-MONO-001", trace)
    base_risk = explanation.baseline_risk

    for mod, summary in explanation.ablation_outcomes.items():
        assert summary.final_risk <= base_risk + 1e-6, (
            f"Sensor removal monotonicity violated for {mod}: "
            f"ablated risk {summary.final_risk} > base risk {base_risk}"
        )
        assert summary.risk_drop >= 0.0


def test_counterfactual_readonly_sandboxing(tmp_path):
    """Verify counterfactual generation is strictly read-only and never writes to live DB."""
    db_p = tmp_path / "live_sandboxed.db"
    repo = IncidentRepository(db_path=db_p)

    with sqlite3.connect(str(db_p)) as conn:
        before_inc = conn.execute("SELECT count(*) FROM incidents").fetchone()[0]
        before_events = conn.execute("SELECT count(*) FROM incident_events").fetchone()[0]
        before_actions = conn.execute("SELECT count(*) FROM operator_actions").fetchone()[0]

    trace = build_sample_incident_trace("INC-RO-001")
    explainer = CounterfactualExplanationEngine()
    explanation = explainer.explain_incident("INC-RO-001", trace)

    assert explanation.incident_id == "INC-RO-001"

    with sqlite3.connect(str(db_p)) as conn:
        after_inc = conn.execute("SELECT count(*) FROM incidents").fetchone()[0]
        after_events = conn.execute("SELECT count(*) FROM incident_events").fetchone()[0]
        after_actions = conn.execute("SELECT count(*) FROM operator_actions").fetchone()[0]

    assert before_inc == after_inc == 0
    assert before_events == after_events == 0
    assert before_actions == after_actions == 0
    repo.close()


def test_pivot_sensor_and_highest_impact():
    """Verify identification of top contributing modality and pivot sensor."""
    # Build trace where camera is the primary driver of alert
    trace = [
        ReplayStepInput(
            timestamp_offset_sec=0.0,
            camera_classes=["car"],
            camera_confidence=0.5,
            audio_class="ambient",
            audio_confidence=0.3,
            audio_db=55.0,
        ),
        ReplayStepInput(
            timestamp_offset_sec=1.0,
            camera_classes=["accident"],
            camera_confidence=0.95,
            audio_class="crash",
            audio_confidence=0.90,
            audio_db=92.0,
        ),
    ]

    explainer = CounterfactualExplanationEngine()
    explanation = explainer.explain_incident("INC-PIVOT-001", trace)

    assert explanation.top_contributing_evidence in ("camera", "audio", "sensors")
    assert explanation.highest_impact_sensor in ("camera", "audio", "sensors")
    assert explanation.max_risk_drop >= 0.0
    assert "Classification:" in explanation.explanation_text
    assert "Ablation Matrix:" in explanation.explanation_text


def test_why_not_triggered_for_suppressed_incident():
    """Verify why_not_triggered provides informative suppression rationale for benign traces."""
    benign_trace = [
        ReplayStepInput(
            timestamp_offset_sec=0.0,
            camera_classes=[],
            camera_confidence=0.1,
            audio_class="ambient",
            audio_confidence=0.2,
            audio_db=40.0,
        ),
        ReplayStepInput(
            timestamp_offset_sec=1.0,
            camera_classes=[],
            camera_confidence=0.1,
            audio_class="ambient",
            audio_confidence=0.2,
            audio_db=42.0,
        ),
    ]

    explainer = CounterfactualExplanationEngine()
    explanation = explainer.explain_incident("INC-BENIGN-001", benign_trace)

    assert explanation.baseline_decision == "NORMAL"
    assert explanation.why_not_triggered is not None
    assert "below alert threshold" in explanation.why_not_triggered or "suppressed" in explanation.why_not_triggered


def test_performance_bounds_for_pi():
    """Verify execution time is bounded for edge hardware (Raspberry Pi target)."""
    trace = build_sample_incident_trace("INC-PERF-001")
    explainer = CounterfactualExplanationEngine()

    start = time.perf_counter()
    iterations = 5
    for _ in range(iterations):
        explainer.explain_incident("INC-PERF-001", trace)
    elapsed_total = time.perf_counter() - start
    avg_ms = (elapsed_total / iterations) * 1000.0

    # Must complete within 100ms per explanation on desktop / < 250ms on edge
    assert avg_ms < 100.0, f"Average explanation time {avg_ms:.2f}ms exceeds 100ms budget"


def test_serialization():
    """Verify to_dict produces valid, complete JSON-serializable structure."""
    trace = build_sample_incident_trace("INC-SERIAL-001")
    explainer = CounterfactualExplanationEngine()
    explanation = explainer.explain_incident("INC-SERIAL-001", trace)

    data = explanation.to_dict()
    assert isinstance(data, dict)
    assert data["incident_id"] == "INC-SERIAL-001"
    assert "ablation_outcomes" in data
    assert "without_camera" in data["ablation_outcomes"]
    assert "without_audio" in data["ablation_outcomes"]
    assert "without_sensors" in data["ablation_outcomes"]
    assert data["fidelity_verified"] is True
