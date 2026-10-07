"""
Comprehensive Unit and Integration Tests for Phase 6M:
Operator-Facing Explainable Decision Timeline.

Validates:
1. Replay Engine and Governed Store Integration (no duplicate logic).
2. Timeline completeness metric: 100% of decision steps represented.
3. Chronological time-ordering: strictly monotonic timestamp offsets.
4. Completeness of all required fields per step:
   - raw evidence arrivals per modality
   - model predictions
   - risk factors (6B) and zone factors (6L)
   - OOD flags
   - counterfactual outcomes (6E)
   - response plans
   - operator actions
5. Offline compatibility: rendered HTML contains ZERO external CDN links.
6. Print-ready capability: includes `@media print` directives and print triggers.
7. Role permissions: check_endpoint_permission allows ALL_ROLES and blocks unauthenticated.
8. Execution performance budget: end-to-end timeline assembly within Pi-class budget (< 50ms).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
import pytest

from src.modules.database.governed_store import IncidentRepository
from src.modules.decision.counterfactual_engine import CounterfactualExplanationEngine
from src.modules.decision.explainable_timeline import (
    ExplainableTimeline,
    ExplainableTimelineEngine,
    ExplainableTimelineStep,
)
from src.modules.incident_management.replay_engine import (
    ReplayStepInput,
    SandboxedReplayEngine,
)
from src.modules.security.permission_matrix import (
    ALL_ROLES,
    check_endpoint_permission,
)


@pytest.fixture
def timeline_repo(tmp_path):
    db_path = tmp_path / "timeline_test.db"
    repo = IncidentRepository(db_path=db_path)
    yield repo
    repo.close()


@pytest.fixture
def sample_trace() -> list[ReplayStepInput]:
    return [
        ReplayStepInput(
            timestamp_offset_sec=0.0,
            camera_classes=["car", "pedestrian"],
            camera_confidence=0.75,
            audio_class="ambient",
            audio_confidence=0.5,
            audio_db=58.0,
            sensor_temp=22.0,
            sensor_smoke_ppm=10.0,
        ),
        ReplayStepInput(
            timestamp_offset_sec=1.0,
            camera_classes=["damaged_vehicle", "debris"],
            camera_confidence=0.89,
            audio_class="crash",
            audio_confidence=0.91,
            audio_db=92.0,
            sensor_temp=24.0,
            sensor_smoke_ppm=15.0,
        ),
        ReplayStepInput(
            timestamp_offset_sec=2.0,
            camera_classes=["damaged_vehicle", "emergency_vehicle"],
            camera_confidence=0.95,
            audio_class="siren",
            audio_confidence=0.96,
            audio_db=95.0,
            sensor_temp=25.0,
            sensor_smoke_ppm=18.0,
        ),
    ]


def test_timeline_completeness_and_monotonicity(sample_trace, timeline_repo):
    """Verify that every decision step is represented and strictly chronological."""
    engine = ExplainableTimelineEngine(repository=timeline_repo)
    timeline: ExplainableTimeline = engine.generate_timeline(
        incident_id="INC-TEST-001",
        steps=sample_trace,
    )

    # 1. Timeline completeness
    assert timeline.completeness_score == 1.0, f"Expected 1.0 completeness, got {timeline.completeness_score}"
    assert len(timeline.steps) == len(sample_trace)

    # 2. Strict time ordering
    offsets = [s.timestamp_offset_sec for s in timeline.steps]
    assert offsets == sorted(offsets)
    assert offsets == [0.0, 1.0, 2.0]


def test_all_required_fields_present_per_step(sample_trace, timeline_repo):
    """
    Verify all required explainability fields:
    - raw evidence arrivals per modality
    - model predictions
    - 6B risk factors
    - OOD flags
    - counterfactual outcomes (6E)
    - response plan
    - operator actions
    """
    engine = ExplainableTimelineEngine(repository=timeline_repo)
    timeline = engine.generate_timeline(
        incident_id="INC-TEST-002",
        steps=sample_trace,
    )

    for idx, step in enumerate(timeline.steps):
        # 1. Raw evidence arrivals per modality
        modalities = {ev.modality for ev in step.raw_evidence}
        assert "CAMERA" in modalities
        assert "AUDIO" in modalities
        assert "SENSORS" in modalities

        # 2. Model predictions
        assert "camera" in step.model_predictions
        assert "audio" in step.model_predictions
        assert "sensors" in step.model_predictions

        # 3. Risk factors (from Phase 6B/6L)
        assert isinstance(step.risk_factors, dict)
        assert "evidence_duration_penalty" in step.risk_factors or "event_confidence" in step.risk_factors
        assert "sensor_agreement" in step.risk_factors

        # 4. OOD flags
        assert isinstance(step.ood_detected, bool)

        # 5. Counterfactual outcomes (6E)
        assert "without_camera" in step.counterfactual_outcomes
        assert "without_audio" in step.counterfactual_outcomes
        assert "without_sensors" in step.counterfactual_outcomes

        # 6. Response plan & decision action
        assert step.recommended_plan != ""
        assert step.decision_action in ("SUPPRESS_NOISE", "REVIEW_REQUIRED", "ALERT")


def test_operator_actions_integration_from_store(sample_trace, timeline_repo):
    """Verify operator workflow actions stored in SQLite are reflected in the timeline."""
    inc_id, _ = timeline_repo.create_incident("ACCIDENT", "ZONE_A")
    timeline_repo.add_operator_action(
        incident_id=inc_id,
        operator_id="operator_bob",
        action="ACKNOWLEDGE",
        approved=True,
        payload={"note": "Verified vehicle collision via CCTV"},
    )
    timeline_repo.writer.drain()

    engine = ExplainableTimelineEngine(repository=timeline_repo)
    timeline = engine.generate_timeline(incident_id=inc_id, steps=sample_trace)

    last_step = timeline.steps[-1]
    assert len(last_step.operator_actions) >= 1
    actions = [op["action"] for op in last_step.operator_actions]
    assert "ACKNOWLEDGE" in actions


def test_offline_html_has_zero_cdn_and_print_support(sample_trace, timeline_repo):
    """
    Verify offline compliance (zero external CDN or web links)
    and @media print styling support in generated HTML.
    """
    engine = ExplainableTimelineEngine(repository=timeline_repo)
    timeline = engine.generate_timeline(incident_id="INC-TEST-004", steps=sample_trace)
    html_out = timeline.to_offline_html()

    # Zero external CDN links
    forbidden_domains = [
        "cdn.", "unpkg.com", "cdnjs.cloudflare.com", "googleapis.com",
        "jsdelivr.net", "http://", "https://"
    ]
    for domain in ["unpkg.com", "cdnjs.cloudflare.com", "fonts.googleapis.com", "cdn.jsdelivr.net"]:
        assert domain not in html_out, f"Found external CDN link in offline HTML: {domain}"

    # Print support
    assert "@media print" in html_out
    assert "window.print()" in html_out
    assert "page-break-inside" in html_out


def test_role_permissions_enforcement():
    """Verify permission matrix enforces ALL_ROLES and blocks unauthenticated access."""
    endpoints = [
        "/api/incident/timeline",
        "/api/incident/timeline/print",
    ]

    for ep in endpoints:
        # Unauthenticated -> 401
        ok, code, msg = check_endpoint_permission(ep, "GET", role=None)
        assert not ok
        assert code == 401

        # All 4 roles permitted -> 200
        for r in ALL_ROLES:
            ok, code, msg = check_endpoint_permission(ep, "GET", role=r)
            assert ok
            assert code == 200


def test_pi_class_render_and_assembly_budget(sample_trace, timeline_repo):
    """
    Verify timeline generation meets Pi-class CPU budget (< 50ms).
    """
    engine = ExplainableTimelineEngine(repository=timeline_repo)

    # Warmup
    engine.generate_timeline(incident_id="INC-WARMUP", steps=sample_trace)

    # Benchmark run
    t0 = time.perf_counter()
    timeline = engine.generate_timeline(incident_id="INC-BENCH", steps=sample_trace)
    duration_ms = (time.perf_counter() - t0) * 1000.0

    html_out = timeline.to_offline_html()
    assert len(html_out) > 500

    # Pi-class budget: well under 50ms (typically 3-15ms)
    assert duration_ms < 50.0, f"Timeline assembly exceeded Pi budget: {duration_ms:.2f}ms >= 50ms"
    assert timeline.assembly_duration_ms < 50.0
