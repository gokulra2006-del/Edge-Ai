"""Unit and integration tests for Phase 6P: Audited Drift-to-Review Loop.

Verifies:
1. Complete state lifecycle transitions (DRIFT_DETECTED -> BATCH_SELECTED ->
   OPERATORS_LABELED -> DATASET_VERSIONED -> CANDIDATE_EVALUATED -> APPROVED/REJECTED).
2. No automatic deployment invariant (live production model remains untouched).
3. Anti-flooding limit enforcement (batch size capped to prevent operator overload).
4. Label leakage prevention (review samples strictly disjoint from frozen test set).
5. Audit completeness and permanent retention of rejected candidate models.
6. RBAC access control (only ENGINEER and COMMANDER can evaluate/decide).
7. Simulated drift active learning experiment (F1 recovery, CI, SYNTHETIC tag).
"""

from __future__ import annotations

import json
import os
import tempfile
import pytest

from src.modules.database.governed_store import IncidentRepository
from src.modules.incident_management.workflow import PermissionDenied
from src.modules.governance.drift_review_loop import (
    DriftLoopState,
    DriftReviewLoop,
    DriftReviewLoopEngine,
    run_simulated_drift_experiment,
)


@pytest.fixture
def temp_repo():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_governed.db")
        repo = IncidentRepository(db_path=db_path)
        try:
            yield repo
        finally:
            repo.close()


def test_drift_loop_state_transitions(temp_repo):
    """Test standard end-to-end happy path state transitions."""
    engine = DriftReviewLoopEngine(repository=temp_repo)

    # 1. Trigger from drift event
    loop = engine.trigger_from_drift_snapshot(
        snapshot_id="snap_20261007_01",
        model_id="YOLO11n-Urban-v2",
        candidate_predictions=[
            {"id": f"pred_{i}", "uncertainty": 0.1 * i, "margin": 0.05}
            for i in range(10)
        ],
        max_batch_size=5,
        actor_id="eng_alice",
        actor_role="ENGINEER",
    )
    assert loop.current_state == DriftLoopState.BATCH_SELECTED
    assert len(loop.uncertain_prediction_ids) == 5
    assert len(loop.stage_history) == 2  # DRIFT_DETECTED and BATCH_SELECTED

    # 2. Operators label
    loop = engine.record_operator_labels(
        loop_id=loop.loop_id,
        operator_labels={
            "pred_9": "EMERGENCY_VEHICLE",
            "pred_8": "NORMAL_TRAFFIC",
            "pred_7": "ACCIDENT",
        },
        actor_id="op_bob",
        actor_role="OPERATOR",
    )
    assert loop.current_state == DriftLoopState.OPERATORS_LABELED
    assert len(loop.operator_labeled_samples) == 3

    # 3. Version review dataset
    loop = engine.create_dataset_version(
        loop_id=loop.loop_id,
        dataset_version_hash="sha256_dataset_v42",
        actor_id="eng_alice",
        actor_role="ENGINEER",
    )
    assert loop.current_state == DriftLoopState.DATASET_VERSIONED
    assert loop.dataset_version_hash == "sha256_dataset_v42"

    # 4. Offline candidate evaluation
    loop = engine.evaluate_candidate_offline(
        loop_id=loop.loop_id,
        candidate_model_version="YOLO11n-Urban-v2.1-candidate",
        baseline_f1=0.720,
        candidate_f1=0.865,
        frozen_test_set_hash="sha256_frozen_test_v1",
        actor_id="eng_alice",
        actor_role="ENGINEER",
    )
    assert loop.current_state == DriftLoopState.CANDIDATE_EVALUATED
    assert loop.candidate_model_version == "YOLO11n-Urban-v2.1-candidate"
    assert loop.baseline_f1 == 0.720
    assert loop.candidate_f1 == 0.865
    assert loop.delta_f1 == pytest.approx(0.145)

    # 5. Human signoff: Approve
    loop = engine.decide_candidate(
        loop_id=loop.loop_id,
        decision="APPROVED",
        reason="F1 improvement +14.5% exceeds required +5% threshold on frozen test set",
        actor_id="cmdr_vance",
        actor_role="COMMANDER",
    )
    assert loop.current_state == DriftLoopState.APPROVED
    assert loop.decision_reason.startswith("F1 improvement")
    assert loop.decision_actor_id == "cmdr_vance"

    # Verify persisted in repo
    persisted = engine.get_loop(loop.loop_id)
    assert persisted is not None
    assert persisted.current_state == DriftLoopState.APPROVED
    assert len(persisted.stage_history) == 6


def test_no_automatic_deployment_guarantee(temp_repo):
    """Verify that evaluated candidates are never automatically promoted or deployed."""
    engine = DriftReviewLoopEngine(repository=temp_repo)

    loop = engine.trigger_from_drift_snapshot(
        snapshot_id="snap_test",
        model_id="AcousticNet-v1",
        candidate_predictions=[{"id": "p1", "uncertainty": 0.8}],
        max_batch_size=5,
        actor_id="eng_alice",
        actor_role="ENGINEER",
    )
    engine.record_operator_labels(loop.loop_id, {"p1": "SIREN"}, "op_bob", "OPERATOR")
    engine.create_dataset_version(loop.loop_id, "hash_123", "eng_alice", "ENGINEER")
    
    # Offline evaluation completes
    evaluated_loop = engine.evaluate_candidate_offline(
        loop_id=loop.loop_id,
        candidate_model_version="AcousticNet-v1.1-cand",
        baseline_f1=0.60,
        candidate_f1=0.85,
        frozen_test_set_hash="test_hash_fixed",
        actor_id="eng_alice",
        actor_role="ENGINEER",
    )

    # State must be CANDIDATE_EVALUATED, NOT DEPLOYED or ACTIVE
    assert evaluated_loop.current_state == DriftLoopState.CANDIDATE_EVALUATED
    assert evaluated_loop.decision_reason is None

    # Approval registers candidate as approved, but NEVER auto-activates as live model
    approved_loop = engine.decide_candidate(
        loop.loop_id,
        decision="APPROVED",
        reason="Approved by engineer for shadow staging",
        actor_id="eng_alice",
        actor_role="ENGINEER",
    )
    assert approved_loop.current_state == DriftLoopState.APPROVED
    # Stage name must explicitly reflect human governance
    assert approved_loop.stage_history[-1].stage == DriftLoopState.APPROVED


def test_flooding_limit_enforcement(temp_repo):
    """Verify that review batch size is strictly bounded by max limits to prevent operator flooding."""
    engine = DriftReviewLoopEngine(repository=temp_repo)

    # Provide 100 candidate predictions
    candidates = [{"id": f"p_{i}", "uncertainty": float(i) / 100.0} for i in range(100)]

    # Request batch size 10
    loop1 = engine.trigger_from_drift_snapshot(
        snapshot_id="snap_1",
        model_id="YOLO-1",
        candidate_predictions=candidates,
        max_batch_size=10,
        actor_id="eng_1",
        actor_role="ENGINEER",
    )
    assert len(loop1.uncertain_prediction_ids) == 10

    # Request batch size 200 (exceeds global cap 50)
    loop2 = engine.trigger_from_drift_snapshot(
        snapshot_id="snap_2",
        model_id="YOLO-1",
        candidate_predictions=candidates,
        max_batch_size=200,
        actor_id="eng_1",
        actor_role="ENGINEER",
    )
    # Must be clamped to default max cap (50)
    assert len(loop2.uncertain_prediction_ids) == 50


def test_label_leakage_prevention(temp_repo):
    """Verify that frozen test set sample IDs are strictly filtered out of review batches."""
    engine = DriftReviewLoopEngine(repository=temp_repo)

    frozen_test_ids = {"test_sample_1", "test_sample_2", "test_sample_3"}

    candidates = [
        {"id": "test_sample_1", "uncertainty": 0.99},  # In frozen test set -> must be excluded
        {"id": "test_sample_2", "uncertainty": 0.98},  # In frozen test set -> must be excluded
        {"id": "train_sample_1", "uncertainty": 0.50}, # Valid
        {"id": "train_sample_2", "uncertainty": 0.40}, # Valid
    ]

    loop = engine.trigger_from_drift_snapshot(
        snapshot_id="snap_leak",
        model_id="YOLO-1",
        candidate_predictions=candidates,
        max_batch_size=10,
        actor_id="eng_1",
        actor_role="ENGINEER",
        frozen_test_set_ids=frozen_test_ids,
    )

    # Selected IDs must not contain any from frozen_test_ids
    assert "test_sample_1" not in loop.uncertain_prediction_ids
    assert "test_sample_2" not in loop.uncertain_prediction_ids
    assert set(loop.uncertain_prediction_ids) == {"train_sample_1", "train_sample_2"}


def test_audit_completeness_and_rejected_candidate_retention(temp_repo):
    """Verify that rejection requires a reason, and rejected candidates are permanently retained."""
    engine = DriftReviewLoopEngine(repository=temp_repo)

    loop = engine.trigger_from_drift_snapshot(
        snapshot_id="snap_reject",
        model_id="YOLO-1",
        candidate_predictions=[{"id": "p1", "uncertainty": 0.9}],
        max_batch_size=5,
        actor_id="eng_1",
        actor_role="ENGINEER",
    )
    engine.record_operator_labels(loop.loop_id, {"p1": "NORMAL"}, "op_1", "OPERATOR")
    engine.create_dataset_version(loop.loop_id, "hash_rej", "eng_1", "ENGINEER")
    engine.evaluate_candidate_offline(
        loop.loop_id,
        candidate_model_version="YOLO-1-bad-cand",
        baseline_f1=0.80,
        candidate_f1=0.74,  # Regressed!
        frozen_test_set_hash="test_hash_fixed",
        actor_id="eng_1",
        actor_role="ENGINEER",
    )

    # Rejection without reason must fail
    with pytest.raises(ValueError, match="Mandatory decision reason"):
        engine.decide_candidate(
            loop.loop_id,
            decision="REJECTED",
            reason="",
            actor_id="cmdr_vance",
            actor_role="COMMANDER",
        )

    # Valid rejection
    rej_loop = engine.decide_candidate(
        loop.loop_id,
        decision="REJECTED",
        reason="Model performance regressed from 0.80 to 0.74 F1 (-6%). Candidate discarded.",
        actor_id="cmdr_vance",
        actor_role="COMMANDER",
    )
    assert rej_loop.current_state == DriftLoopState.REJECTED
    assert rej_loop.candidate_model_version == "YOLO-1-bad-cand"

    # Verify candidate is retained in database and accessible
    retrieved = engine.get_loop(loop.loop_id)
    assert retrieved is not None
    assert retrieved.current_state == DriftLoopState.REJECTED
    assert retrieved.candidate_model_version == "YOLO-1-bad-cand"
    assert "regressed" in retrieved.decision_reason

    # Audit HTML export check
    html = retrieved.to_html()
    assert "REJECTED (RETAINED IN AUDIT)" in html
    assert "YOLO-1-bad-cand" in html
    assert "Mandatory Decision Reason" in html


def test_role_authorization_restrictions(temp_repo):
    """Verify that unauthorized roles cannot evaluate or sign off on candidates."""
    engine = DriftReviewLoopEngine(repository=temp_repo)

    loop = engine.trigger_from_drift_snapshot(
        snapshot_id="snap_auth",
        model_id="YOLO-1",
        candidate_predictions=[{"id": "p1", "uncertainty": 0.5}],
        max_batch_size=5,
        actor_id="eng_1",
        actor_role="ENGINEER",
    )
    engine.record_operator_labels(loop.loop_id, {"p1": "NORMAL"}, "op_1", "OPERATOR")
    engine.create_dataset_version(loop.loop_id, "hash_auth", "eng_1", "ENGINEER")

    # VIEWER cannot evaluate
    with pytest.raises((PermissionDenied, PermissionError), match="Role VIEWER not authorized"):
        engine.evaluate_candidate_offline(
            loop.loop_id,
            candidate_model_version="cand_v",
            baseline_f1=0.7,
            candidate_f1=0.8,
            frozen_test_set_hash="hash",
            actor_id="viewer_bob",
            actor_role="VIEWER",
        )

    # Valid evaluation by ENGINEER
    engine.evaluate_candidate_offline(
        loop.loop_id,
        candidate_model_version="cand_v",
        baseline_f1=0.7,
        candidate_f1=0.8,
        frozen_test_set_hash="hash",
        actor_id="eng_1",
        actor_role="ENGINEER",
    )

    # OPERATOR cannot decide / approve candidate
    with pytest.raises((PermissionDenied, PermissionError), match="Role OPERATOR not authorized"):
        engine.decide_candidate(
            loop.loop_id,
            decision="APPROVED",
            reason="Operator approving",
            actor_id="op_1",
            actor_role="OPERATOR",
        )


def test_simulated_drift_experiment_metrics():
    """Verify simulated active learning vs random selection experiment produces 6A metrics and SYNTHETIC tag."""
    results = run_simulated_drift_experiment(sample_budget_steps=[10, 30, 50], seed=42)
    assert len(results) == 6  # 3 steps * 2 strategies (active_uncertainty, random_sampling)

    for res in results:
        assert res.data_tag == "SYNTHETIC"
        assert res.ci_lower <= res.recovered_f1 <= res.ci_upper
        assert res.samples_labeled in [10, 30, 50]
        assert res.baseline_f1 > res.drifted_f1

    # Active uncertainty should achieve equal or better recovery rate than random sampling at equal budget
    active_res = {r.samples_labeled: r for r in results if r.strategy == "active_uncertainty"}
    random_res = {r.samples_labeled: r for r in results if r.strategy == "random_sampling"}

    for budget in [10, 30, 50]:
        assert active_res[budget].recovered_f1 >= random_res[budget].recovered_f1
        assert active_res[budget].recovery_rate >= random_res[budget].recovery_rate
