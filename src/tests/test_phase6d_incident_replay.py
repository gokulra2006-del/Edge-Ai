"""Tests for Phase 6D: Incident Replay and Digital Twin."""
from __future__ import annotations

import sqlite3
import pytest

from replay.__main__ import build_sample_incident_trace
from src.modules.incident_management.replay_engine import (
    ReplayStepInput,
    SandboxedReplayEngine,
)
from src.modules.database.governed_store import IncidentRepository


def test_replay_determinism():
    """Verify unmodified replay reproduces bit-exact identical hash and decisions across runs."""
    trace = build_sample_incident_trace("INC-DET-001")
    engine = SandboxedReplayEngine()

    run1 = engine.execute_replay("INC-DET-001", trace)
    run2 = engine.execute_replay("INC-DET-001", trace)

    assert run1.final_decision == run2.final_decision
    assert run1.final_risk == run2.final_risk
    assert run1.hash_digest == run2.hash_digest
    assert len(run1.timeline) == len(run2.timeline)
    assert run1.mismatch_count == 0


def test_sandbox_isolation_no_database_writes(tmp_path):
    """Verify replay execution NEVER mutates live incident tables."""
    db_p = tmp_path / "live_test.db"
    repo = IncidentRepository(db_path=db_p)

    # Initial counts
    with sqlite3.connect(str(db_p)) as conn:
        c1 = conn.execute("SELECT count(*) FROM incidents").fetchone()[0]
        c2 = conn.execute("SELECT count(*) FROM incident_events").fetchone()[0]

    # Run replay simulator
    trace = build_sample_incident_trace("INC-SANDBOX-TEST")
    engine = SandboxedReplayEngine()
    result = engine.execute_replay("INC-SANDBOX-TEST", trace)

    assert result.sandbox_verified is True

    # Final counts must be strictly unchanged
    with sqlite3.connect(str(db_p)) as conn:
        c1_post = conn.execute("SELECT count(*) FROM incidents").fetchone()[0]
        c2_post = conn.execute("SELECT count(*) FROM incident_events").fetchone()[0]

    assert c1 == c1_post == 0
    assert c2 == c2_post == 0
    repo.close()


def test_counterfactual_fault_controls():
    """Verify fault controls (camera failure, dropout, conflicting sensors) perturb decision."""
    trace = build_sample_incident_trace("INC-CF-TEST")
    engine = SandboxedReplayEngine()

    # 1. Clean baseline
    clean_run = engine.execute_replay("INC-CF-TEST", trace)

    # 2. Camera failure
    cam_fail_run = engine.execute_replay("INC-CF-TEST", trace, camera_failure=True)
    assert cam_fail_run.is_counterfactual is True
    # Camera failure degrades device health and sets camera conf to 0
    assert cam_fail_run.timeline[-1].risk_factors["device_health"] < clean_run.timeline[-1].risk_factors["device_health"]

    # 3. Conflicting sensors
    conflict_run = engine.execute_replay("INC-CF-TEST", trace, conflicting_sensors=True)
    assert conflict_run.is_counterfactual is True
    assert any(step.ood_detected for step in conflict_run.timeline)

    # 4. Alternative operator decision
    op_run = engine.execute_replay("INC-CF-TEST", trace, operator_action="FALSE_ALARM")
    assert op_run.is_counterfactual is True
    last_step = op_run.timeline[-1]
    assert last_step.operator_action == "FALSE_ALARM"
    assert "FALSE_ALARM" in last_step.recommended_plan


def test_mismatch_detection_against_baseline():
    """Verify divergence from baseline decision is flagged as replay mismatch."""
    trace = build_sample_incident_trace("INC-MISMATCH")
    engine = SandboxedReplayEngine()

    # Intentionally expect AMBULANCE when trace produces ACCIDENT
    result = engine.execute_replay("INC-MISMATCH", trace, baseline_decision="AMBULANCE")
    assert result.mismatch_count > 0
    assert any(s.mismatch_detected for s in result.timeline)
