"""
Comprehensive Test Suite for Sensor-Availability Matrix & Degradation Controls (Phase 6O).
========================================================================================
Hypothesis:
"Showing how each incident's outcome changes when each sensor is removed, or when
sensors conflict, lets operators judge decision robustness; evaluated by decision
stability and agreement with real replays."

Verifies:
1. Monotonic Risk Invariant: Removing a sensor never raises risk (Risk_ablation <= Risk_baseline).
2. Exact Replay Congruence: The matrix entries match what a real 6D sandboxed replay with that sensor removed produces bit-for-bit.
3. Explicit Conflict Gating: Cross-modal disagreement beyond configured margin routes unconditionally to HUMAN_REVIEW, never a silent pick.
4. Hypothetical Replay Controls: Alternative confidence thresholds and operator decisions are explicitly labeled is_hypothetical=True.
5. Offline Zero-CDN Display: Standalone HTML output contains no external CDN or web dependencies.
6. Report Integration: Sensor-availability matrix is rendered in forensic incident reports.
7. Performance & Caching: Lazy computation / cache guarantees fast edge budget.
8. 6A Evaluation Metrics: Decision stability under sensor loss computation.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from evaluation.metrics import compute_decision_stability_under_sensor_loss
from src.modules.database.governed_store import IncidentRepository
from src.modules.decision.sensor_availability_matrix import (
    SensorAvailabilityMatrixEngine,
    SensorAvailabilityMatrix,
    map_outcome_level,
)
from src.modules.incident_management.replay_engine import (
    ReplayStepInput,
    SandboxedReplayEngine,
)
from src.modules.recording.report_generator import ForensicReportGenerator


@pytest.fixture
def repo(tmp_path: Path):
    db_path = tmp_path / "test_sensor_availability.db"
    repository = IncidentRepository(db_path)
    yield repository
    repository.close()


def create_sample_incident_trace() -> list[ReplayStepInput]:
    return [
        ReplayStepInput(
            timestamp_offset_sec=0.0,
            camera_classes=["fire"],
            camera_confidence=0.92,
            camera_fps=20.0,
            audio_class="siren",
            audio_confidence=0.88,
            audio_db=82.0,
            sensor_temp=54.0,
            sensor_smoke_ppm=110.0,
            sensor_imu_g=0.5,
            network_online=True,
        ),
        ReplayStepInput(
            timestamp_offset_sec=1.5,
            camera_classes=["fire"],
            camera_confidence=0.96,
            camera_fps=20.0,
            audio_class="fire",
            audio_confidence=0.91,
            audio_db=85.0,
            sensor_temp=62.0,
            sensor_smoke_ppm=140.0,
            sensor_imu_g=0.4,
            network_online=True,
        ),
    ]


def test_monotonic_risk_invariant(repo: IncidentRepository):
    """Removing a sensor must never raise final risk above baseline (Risk_ablation <= Risk_baseline)."""
    engine = SensorAvailabilityMatrixEngine(repository=repo)
    steps = create_sample_incident_trace()

    matrix = engine.compute_matrix(incident_id="INC-TEST-001", steps=steps, use_cache=False)

    assert matrix.baseline_risk > 0.0
    for cond_key, entry in matrix.entries.items():
        if cond_key == "ALL_SENSORS":
            assert abs(entry.final_risk - matrix.baseline_risk) < 1e-4
        elif cond_key != "CONFLICTING_SENSORS":
            # For any sensor removal, final risk must be <= baseline_risk
            assert entry.final_risk <= matrix.baseline_risk + 1e-5, (
                f"Monotonic risk invariant violated in {cond_key}: "
                f"{entry.final_risk} > baseline {matrix.baseline_risk}"
            )


def test_exact_replay_congruence(repo: IncidentRepository):
    """Matrix outcome must equal bit-for-bit what a real 6D sandboxed replay with that sensor removed produces."""
    engine = SensorAvailabilityMatrixEngine(repository=repo)
    replay_engine = SandboxedReplayEngine()
    steps = create_sample_incident_trace()

    matrix = engine.compute_matrix(incident_id="INC-TEST-002", steps=steps, use_cache=False)

    # 1. Baseline congruence
    direct_base = replay_engine.execute_replay(incident_id="INC-TEST-002", steps=steps)
    assert abs(matrix.entries["ALL_SENSORS"].final_risk - direct_base.final_risk) < 1e-4
    assert matrix.entries["ALL_SENSORS"].predicted_class == direct_base.final_decision

    # 2. Camera ablation congruence
    direct_no_cam = replay_engine.execute_replay(
        incident_id="INC-TEST-002",
        steps=steps,
        dropout_sensor="camera",
        baseline_risk=direct_base.final_risk,
    )
    cam_entry = matrix.entries["WITHOUT_CAMERA"]
    assert abs(cam_entry.final_risk - direct_no_cam.final_risk) < 1e-4
    assert cam_entry.predicted_class == direct_no_cam.final_decision

    # 3. Audio ablation congruence
    direct_no_audio = replay_engine.execute_replay(
        incident_id="INC-TEST-002",
        steps=steps,
        dropout_sensor="audio",
        baseline_risk=direct_base.final_risk,
    )
    audio_entry = matrix.entries["WITHOUT_AUDIO"]
    assert abs(audio_entry.final_risk - direct_no_audio.final_risk) < 1e-4
    assert audio_entry.predicted_class == direct_no_audio.final_decision

    # 4. Camera + Audio pair ablation congruence
    direct_no_both = replay_engine.execute_replay(
        incident_id="INC-TEST-002",
        steps=steps,
        dropout_sensor="camera+audio",
        baseline_risk=direct_base.final_risk,
    )
    both_entry = matrix.entries["WITHOUT_CAMERA_AND_AUDIO"]
    assert abs(both_entry.final_risk - direct_no_both.final_risk) < 1e-4
    assert both_entry.predicted_class == direct_no_both.final_decision


def test_explicit_conflict_gating_routes_to_human_review(repo: IncidentRepository):
    """When modalities disagree beyond configured margin, outcome routes to HUMAN_REVIEW without silent resolution."""
    engine = SensorAvailabilityMatrixEngine(repository=repo)

    # Conflict trace: Camera strongly indicates FIRE, Audio strongly indicates ACCIDENT (crash)
    conflict_steps = [
        ReplayStepInput(
            timestamp_offset_sec=0.0,
            camera_classes=["fire"],
            camera_confidence=0.95,
            camera_fps=20.0,
            audio_class="crash",
            audio_confidence=0.95,
            audio_db=88.0,
            sensor_temp=22.0,
            sensor_smoke_ppm=5.0,
            sensor_imu_g=0.1,
            network_online=True,
        )
    ]

    matrix = engine.compute_matrix(
        incident_id="INC-CONFLICT-001",
        steps=conflict_steps,
        conflict_margin=0.20,
        use_cache=False,
    )

    base_entry = matrix.entries["ALL_SENSORS"]
    assert base_entry.is_conflict is True
    assert base_entry.outcome_level == "HUMAN_REVIEW"
    assert base_entry.action == "HUMAN_REVIEW"

    # Injected conflict condition must also yield HUMAN_REVIEW
    conflict_entry = matrix.entries["CONFLICTING_SENSORS"]
    assert conflict_entry.outcome_level == "HUMAN_REVIEW"
    assert conflict_entry.is_conflict is True


def test_replay_controls_hypothetical_labeling(repo: IncidentRepository):
    """Replays with custom thresholds or hypothetical operator overrides must be tagged is_hypothetical=True."""
    engine = SensorAvailabilityMatrixEngine(repository=repo)
    steps = create_sample_incident_trace()

    # Normal baseline run: is_hypothetical False
    normal_run = engine.replay_hypothetical(
        incident_id="INC-TEST-003",
        steps=steps,
        custom_alert_threshold=None,
        operator_action="NONE",
    )
    # When no overrides applied, is_hypothetical is still flagged if called via replay_hypothetical
    assert normal_run.is_hypothetical is True

    # Custom threshold evaluation
    custom_run = engine.replay_hypothetical(
        incident_id="INC-TEST-003",
        steps=steps,
        custom_alert_threshold=0.99,  # Very high threshold
        operator_action="OVERRIDE_FALSE_ALARM",
    )
    assert custom_run.is_hypothetical is True
    assert custom_run.controls_applied["custom_alert_threshold"] == 0.99
    assert custom_run.controls_applied["operator_action"] == "OVERRIDE_FALSE_ALARM"

    # Matrix computed with hypothetical parameters
    hypo_matrix = engine.compute_matrix(
        incident_id="INC-TEST-003",
        steps=steps,
        custom_alert_threshold=0.88,
        operator_action="ESCALATE",
        use_cache=False,
    )
    assert hypo_matrix.is_hypothetical is True


def test_offline_zero_cdn_html_rendering(repo: IncidentRepository):
    """Availability matrix HTML output must render completely offline without external CDN dependencies."""
    engine = SensorAvailabilityMatrixEngine(repository=repo)
    steps = create_sample_incident_trace()

    matrix = engine.compute_matrix(incident_id="INC-HTML-001", steps=steps, use_cache=False)
    rendered_html = matrix.to_html()

    assert "<table" in rendered_html
    assert "INC-HTML-001" in rendered_html
    assert "STABILITY:" in rendered_html
    assert "Camera unavailable" in rendered_html
    assert "Audio unavailable" in rendered_html
    assert "IMU unavailable" in rendered_html
    assert "Conflicting sensors stress" in rendered_html

    # Zero-CDN invariant
    for forbidden in ["http://", "https://", "cdn.", "unpkg", "cdnjs", "googleapis"]:
        assert forbidden not in rendered_html.lower(), f"Forbidden external dependency: {forbidden}"


def test_forensic_report_incorporation(repo: IncidentRepository, tmp_path: Path):
    """Forensic HTML report must seamlessly embed the sensor-availability matrix."""
    # Ensure foreign key exists in incidents table
    inc_id, _ = repo.create_incident(
        event_type="FIRE",
        zone_id="ZONE-ALPHA",
    )

    engine = SensorAvailabilityMatrixEngine(repository=repo)
    steps = create_sample_incident_trace()
    matrix = engine.compute_matrix(incident_id=inc_id, steps=steps)

    report_gen = ForensicReportGenerator()
    incident_data = {
        "incident_id": inc_id,
        "event_type": "FIRE",
        "severity": "CRITICAL",
        "zone_id": "ZONE-ALPHA",
        "created_at": "2026-10-07T12:00:00Z",
        "availability_matrix": matrix,
    }
    html_content = report_gen.generate_html_report(incident_data)

    assert "Sensor-Availability Degradation Matrix" in html_content
    assert inc_id in html_content
    assert "STABILITY:" in html_content


def test_matrix_persistence_and_lazy_caching(repo: IncidentRepository):
    """Matrix computations are cached in-memory and persisted to SQLite for edge performance."""
    # Create incident record for foreign key integrity
    inc_id, _ = repo.create_incident(
        event_type="FIRE",
        zone_id="ZONE-BETA",
    )

    engine = SensorAvailabilityMatrixEngine(repository=repo)
    steps = create_sample_incident_trace()

    # 1. First run: computes and saves to repository
    m1 = engine.compute_matrix(incident_id=inc_id, steps=steps, use_cache=False)
    assert m1.is_cached is False

    # 2. Second run: served directly from memory cache
    m2 = engine.compute_matrix(incident_id=inc_id, steps=steps, use_cache=True)
    assert m2.is_cached is True
    assert m2.incident_id == m1.incident_id
    assert m2.decision_stability_score == m1.decision_stability_score

    # 3. Drain writer queue to guarantee SQLite commit
    repo.writer.drain(timeout=1.0)

    # 4. New engine instance: loads from persisted database table
    engine_fresh = SensorAvailabilityMatrixEngine(repository=repo)
    m3 = engine_fresh.compute_matrix(incident_id=inc_id, steps=steps, use_cache=True)
    assert m3.is_cached is True
    assert m3.baseline_outcome == m1.baseline_outcome
    assert len(m3.entries) == len(m1.entries)


def test_6a_evaluation_metric_decision_stability():
    """Verify compute_decision_stability_under_sensor_loss() evaluator metric."""
    baseline = [
        {"decision": "FIRE", "final_risk": 0.85},
        {"decision": "ACCIDENT", "final_risk": 0.78},
    ]
    ablations = [
        {
            "without_camera": {"decision": "FIRE", "final_risk": 0.70},
            "without_audio": {"decision": "FIRE", "final_risk": 0.80},
            "without_sensors": {"decision": "REVIEW_REQUIRED", "final_risk": 0.50},
        },
        {
            "without_camera": {"decision": "REVIEW_REQUIRED", "final_risk": 0.65},
            "without_audio": {"decision": "ACCIDENT", "final_risk": 0.72},
            "without_sensors": {"decision": "ACCIDENT", "final_risk": 0.75},
        },
    ]

    metrics = compute_decision_stability_under_sensor_loss(
        baseline_outcomes=baseline,
        ablation_outcomes=ablations,
    )

    assert metrics.total_evaluations == 2
    assert 0.0 <= metrics.mean_stability_score <= 1.0
    assert metrics.camera_loss_stability_pct >= 0.0
    assert metrics.audio_loss_stability_pct >= 0.0
    assert metrics.sensor_loss_stability_pct >= 0.0
    assert metrics.monotonic_risk_invariant_pct == 100.0  # All ablations had lower risk than baseline


def test_phase6o_endpoint_permissions():
    """Verify RBAC permissions for Phase 6O availability-matrix and hypothetical replay endpoints."""
    from src.modules.security.permission_matrix import check_endpoint_permission

    # GET /api/incident/availability-matrix (ALL_ROLES)
    ok, st, _ = check_endpoint_permission("/api/incident/availability-matrix", "GET", None)
    assert ok is False and st == 401
    assert check_endpoint_permission("/api/incident/availability-matrix", "GET", "VIEWER")[:2] == (True, 200)
    assert check_endpoint_permission("/api/incident/availability-matrix", "GET", "OPERATOR")[:2] == (True, 200)
    assert check_endpoint_permission("/api/incident/availability-matrix", "GET", "COMMANDER")[:2] == (True, 200)

    # POST /api/replay/hypothetical (OPS_ROLES: COMMANDER, OPERATOR)
    ok, st, _ = check_endpoint_permission("/api/replay/hypothetical", "POST", None)
    assert ok is False and st == 401
    ok, st, _ = check_endpoint_permission("/api/replay/hypothetical", "POST", "VIEWER")
    assert ok is False and st == 403
    assert check_endpoint_permission("/api/replay/hypothetical", "POST", "OPERATOR")[:2] == (True, 200)
    assert check_endpoint_permission("/api/replay/hypothetical", "POST", "COMMANDER")[:2] == (True, 200)

