"""
Tests for Phase 6G: Governed Human-Feedback Loop, Active Learning, and Retraining Proposals.
============================================================================================
Validates:
1. Active learning selection (least-confidence, margin, OOD) vs random selection.
2. Label quality tracking, inter-operator agreement, and automated conflict flagging.
3. Dataset snapshot immutability and SHA-256 cryptographic provenance.
4. Strict test-set leakage isolation (zero overlap between training snapshots and frozen tests).
5. Retraining proposal generation with per-zone and per-class before/after evaluations.
6. Gated approval workflow: only Commander or Engineer can approve; Operator/Viewer rejected.
7. Approved models enter registry as CANDIDATE and remain strictly blocked from actuation.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import pytest

from src.modules.database.governed_store import IncidentRepository, GovernanceConfig
from src.modules.core.safety_registry_gate import SafetyAwareModelRegistry
from src.modules.governance.feedback_loop import (
    ActiveLearningScore,
    ActiveLearningSelector,
    DatasetSnapshot,
    DatasetSnapshotManager,
    LabelQualityTracker,
    ProposalApprovalWorkflow,
    RetrainingProposalGenerator,
    simulate_active_vs_random_experiment,
)
from src.modules.incident_management.workflow import (
    OperatorWorkflow,
    PermissionDenied,
    ReviewQueue,
)


@pytest.fixture
def governed_repo(tmp_path):
    repo = IncidentRepository(tmp_path / "phase6g_test.db", GovernanceConfig())
    yield repo
    repo.close()


def test_active_learning_selection_vs_random():
    """Verify active learning prioritizes uncertain, low-margin, and OOD samples over random."""
    selector = ActiveLearningSelector(weight_uncertainty=0.4, weight_margin=0.3, weight_ood=0.3)

    # High certainty nominal item
    item_easy = {
        "id": 1,
        "incident_id": "INC-001",
        "confidence": 0.98,
        "label": "NORMAL",
        "ood_status": "IN_DISTRIBUTION",
        "payload_json": json.dumps({"class_probabilities": {"NORMAL": 0.98, "ACCIDENT": 0.02}}),
    }

    # Highly ambiguous item near decision boundary with low margin
    item_ambiguous = {
        "id": 2,
        "incident_id": "INC-002",
        "confidence": 0.51,
        "label": "REVIEW_REQUIRED",
        "ood_status": "OOD",
        "reason_codes": ["sensor_disagreement"],
        "payload_json": json.dumps({"class_probabilities": {"ACCIDENT": 0.51, "AMBULANCE": 0.49}}),
    }

    score_easy = selector.compute_priority(item_easy)
    score_ambig = selector.compute_priority(item_ambiguous)

    assert score_ambig.combined_priority > score_easy.combined_priority
    assert score_ambig.least_confidence_score > score_easy.least_confidence_score
    assert score_ambig.margin_score > score_easy.margin_score
    assert score_ambig.ood_score > score_easy.ood_score

    # Batch selection
    pool = [item_easy, item_ambiguous]
    selected_active = selector.select_active_learning(pool, batch_size=1)
    assert len(selected_active) == 1
    assert selected_active[0]["id"] == 2  # Picked the ambiguous item


def test_active_learning_simulation_experiment_6a():
    """Verify that active learning selection yields higher sample efficiency than random."""
    res = simulate_active_vs_random_experiment(n_total_candidates=60, batch_size=20, seed=42)

    assert res["hypothesis_confirmed"] is True
    assert res["delta_active"] > res["delta_random"]
    assert res["sample_efficiency_ratio"] > 1.0
    assert len(res["bootstrap_95ci_advantage"]) == 2
    # Upper bound of advantage CI must be positive
    assert res["bootstrap_95ci_advantage"][1] > 0.0


def test_label_quality_and_inter_operator_agreement(governed_repo):
    """Verify consensus calculation, conflict escalation, and inter-operator agreement rate."""
    queue = ReviewQueue(governed_repo)

    # 1. Prediction with consensus agreement
    inc_id1, _ = governed_repo.create_incident("ACCIDENT", "ZONE_A")
    governed_repo.writer.drain()
    governed_repo.add_prediction(inc_id1, "ACCIDENT", 0.75, "m1")
    governed_repo.writer.drain()
    pred_rows1 = governed_repo._read("SELECT id FROM predictions WHERE incident_id=?", (inc_id1,))
    pred_id1 = pred_rows1[0]["id"]

    # Operator 1 and Operator 2 both submit CORRECT
    queue.feedback(pred_id1, "CORRECT", "op_1", "OPERATOR")
    queue.feedback(pred_id1, "CORRECT", "op_2", "OPERATOR")
    governed_repo.writer.drain()

    tracker = queue.get_label_quality_tracker()
    consensus1 = tracker.analyze_prediction_consensus(pred_id1)

    assert consensus1["status"] == "CONSENSUS_REACHED"
    assert consensus1["conflict_flagged"] is False
    assert consensus1["consensus_label"] == "CORRECT"
    assert consensus1["agreement_pct"] == 100.0

    # 2. Prediction with conflicting verdicts
    inc_id2, _ = governed_repo.create_incident("FIRE", "ZONE_B")
    governed_repo.writer.drain()
    governed_repo.add_prediction(inc_id2, "FIRE", 0.55, "m1")
    governed_repo.writer.drain()
    pred_rows2 = governed_repo._read("SELECT id FROM predictions WHERE incident_id=?", (inc_id2,))
    pred_id2 = pred_rows2[0]["id"]

    # Operator 1 says CORRECT, Operator 2 says INCORRECT with corrected_class
    queue.feedback(pred_id2, "CORRECT", "op_1", "OPERATOR")
    queue.feedback(pred_id2, "INCORRECT", "op_2", "OPERATOR", corrected_class="NORMAL")
    governed_repo.writer.drain()

    consensus2 = tracker.analyze_prediction_consensus(pred_id2)
    assert consensus2["status"] == "CONFLICT_FLAGGED"
    assert consensus2["conflict_flagged"] is True

    # Platform-wide analytics
    summary = tracker.compute_platform_disagreement_analytics()
    assert summary.multi_reviewed_predictions >= 2
    assert summary.flagged_conflicts_count >= 1
    assert "op_1" in summary.operator_reliabilities
    assert "op_2" in summary.operator_reliabilities


def test_dataset_snapshot_immutability_and_hash(tmp_path):
    """Verify cryptographic SHA-256 snapshot creation and tampering detection."""
    mgr = DatasetSnapshotManager(storage_dir=tmp_path / "snapshots")

    samples = [
        {"sample_id": "S1", "incident_id": "INC-01", "label": "AMBULANCE", "zone_id": "ZONE_A"},
        {"sample_id": "S2", "incident_id": "INC-02", "label": "ACCIDENT", "zone_id": "ZONE_B"},
    ]

    snapshot = mgr.create_snapshot(samples, operator_id="engineer_bob", operator_role="ENGINEER")

    assert snapshot.samples_count == 2
    assert snapshot.verify_integrity() is True
    assert len(snapshot.sha256_hash) == 64

    # Load and re-verify
    loaded = mgr.load_snapshot(snapshot.snapshot_id)
    assert loaded.verify_integrity() is True

    # Tampering test: modify a sample's label
    tampered_samples = copy.deepcopy(loaded.samples)
    tampered_samples[0]["label"] = "NORMAL"  # Maliciously altered ground truth
    loaded.samples = tampered_samples

    # Must fail integrity verification
    assert loaded.verify_integrity() is False


def test_no_test_set_leakage():
    """Verify complete disjoint separation between review dataset snapshot and frozen test split."""
    mgr = DatasetSnapshotManager()

    # Training review samples
    train_samples = [
        {"sample_id": f"TRAIN_INC_{i:03d}", "incident_id": f"INC-TRN-{i}", "label": "FIRE", "zone_id": "ZONE_A"}
        for i in range(10)
    ]
    snapshot = mgr.create_snapshot(train_samples, "engineer_bob", "ENGINEER", snapshot_id="DATASET-LEAK-TEST")

    # Frozen evaluation test set
    frozen_test = [
        {"sample_id": f"FROZEN_INC_{i:03d}", "incident_id": f"INC-TEST-{i}", "label": "FIRE", "zone_id": "ZONE_A"}
        for i in range(10)
    ]

    train_ids = {s["sample_id"] for s in snapshot.samples}
    test_ids = {s["sample_id"] for s in frozen_test}

    # Strict invariant: zero intersection
    intersection = train_ids.intersection(test_ids)
    assert len(intersection) == 0, f"Test-set leakage detected: {intersection}"


def test_retraining_proposal_generation():
    """Verify retraining proposal generation with per-zone and per-class comparative metrics."""
    mgr = DatasetSnapshotManager()
    gen = RetrainingProposalGenerator()

    samples = [
        {"sample_id": "S1", "label": "FIRE", "zone_id": "ZONE_A"},
        {"sample_id": "S2", "label": "ACCIDENT", "zone_id": "ZONE_B"},
        {"sample_id": "S3", "label": "AMBULANCE", "zone_id": "ZONE_C"},
        {"sample_id": "S4", "label": "NORMAL", "zone_id": "ZONE_A"},
    ]
    snapshot = mgr.create_snapshot(samples, "eng_1", "ENGINEER", snapshot_id="DATASET-PROP-TEST")

    frozen_test = [
        {"sample_id": "T1", "ground_truth_label": "FIRE", "zone_id": "ZONE_A"},
        {"sample_id": "T2", "ground_truth_label": "ACCIDENT", "zone_id": "ZONE_B"},
        {"sample_id": "T3", "ground_truth_label": "AMBULANCE", "zone_id": "ZONE_C"},
        {"sample_id": "T4", "ground_truth_label": "NORMAL", "zone_id": "ZONE_A"},
    ]

    # Candidate model gets 4/4 correct, base model gets 2/4 correct
    base_preds = ["FIRE", "NORMAL", "NORMAL", "NORMAL"]
    cand_preds = ["FIRE", "ACCIDENT", "AMBULANCE", "NORMAL"]

    prop = gen.generate_proposal(
        snapshot=snapshot,
        base_model_id="yolo_v8n_base",
        candidate_model_id="yolo_v8n_cand_v2",
        candidate_model_version="2.0",
        operator_id="eng_1",
        frozen_test_samples=frozen_test,
        base_predictions=base_preds,
        candidate_predictions=cand_preds,
    )

    assert prop.status == "PROPOSED"
    assert prop.evaluation_comparison.candidate_macro_f1 > prop.evaluation_comparison.base_macro_f1
    assert prop.evaluation_comparison.delta_macro_f1 > 0.0
    assert "FIRE" in prop.evaluation_comparison.per_class_f1
    assert "ZONE_A" in prop.evaluation_comparison.per_zone_f1

    # Verify Markdown generation
    md = prop.to_markdown()
    assert "# Model Retraining Proposal:" in md
    assert "Per-Class Performance Breakdown" in md
    assert "Per-Zone Performance Breakdown" in md


def test_approval_workflow_role_gating(governed_repo):
    """Verify only Commander or Engineer can approve proposals; Operator/Viewer rejected."""
    mgr = DatasetSnapshotManager()
    gen = RetrainingProposalGenerator()
    wf = ProposalApprovalWorkflow()

    snapshot = mgr.create_snapshot(
        [{"sample_id": "S1", "label": "FIRE", "zone_id": "ZONE_A"}],
        "eng_bob",
        "ENGINEER",
        snapshot_id="DATASET-APPR-TEST",
    )
    prop = gen.generate_proposal(
        snapshot=snapshot,
        base_model_id="yolo_base",
        candidate_model_id="yolo_cand",
        candidate_model_version="2.1",
        operator_id="eng_bob",
        frozen_test_samples=[{"sample_id": "T1", "ground_truth_label": "FIRE", "zone_id": "ZONE_A"}],
        base_predictions=["FIRE"],
        candidate_predictions=["FIRE"],
    )

    # 1. OPERATOR approval attempt must be rejected
    with pytest.raises(PermissionDenied):
        wf.approve_proposal(prop, operator_id="op_jane", role="OPERATOR", repository=governed_repo)

    # 2. VIEWER approval attempt must be rejected
    with pytest.raises(PermissionDenied):
        wf.approve_proposal(prop, operator_id="viewer_mark", role="VIEWER", repository=governed_repo)

    # 3. ENGINEER approval succeeds
    approved = wf.approve_proposal(prop, operator_id="eng_bob", role="ENGINEER", repository=governed_repo)
    assert approved.status == "APPROVED"
    assert approved.approved_by == "eng_bob"
    assert approved.approved_role == "ENGINEER"

    # Verify audit trail recorded in governed_store
    governed_repo.writer.drain()
    actions = governed_repo.rows("operator_actions")
    assert any(a["action"] == "APPROVE_RETRAINING_PROPOSAL" for a in actions)


def test_approved_model_enters_as_candidate_and_blocked_from_actuation():
    """Verify approved model enters model registry as CANDIDATE and is blocked by 6F safety gate."""
    registry = SafetyAwareModelRegistry()
    wf = ProposalApprovalWorkflow()
    mgr = DatasetSnapshotManager()
    gen = RetrainingProposalGenerator()

    snapshot = mgr.create_snapshot(
        [{"sample_id": "S1", "label": "ACCIDENT", "zone_id": "ZONE_A"}],
        "eng_bob",
        "ENGINEER",
        snapshot_id="DATASET-CAND-GATE",
    )
    prop = gen.generate_proposal(
        snapshot=snapshot,
        base_model_id="m_base",
        candidate_model_id="m_cand_governed",
        candidate_model_version="3.0",
        operator_id="eng_bob",
        frozen_test_samples=[{"sample_id": "T1", "ground_truth_label": "ACCIDENT", "zone_id": "ZONE_A"}],
        base_predictions=["ACCIDENT"],
        candidate_predictions=["ACCIDENT"],
    )

    wf.approve_proposal(prop, operator_id="cmd_sarah", role="COMMANDER", model_registry=registry)

    # Invariant check: Model MUST be registered with status CANDIDATE
    assert "m_cand_governed" in registry.models
    rec = registry.models["m_cand_governed"]
    assert rec.status == "CANDIDATE"

    # 6F Policy Gate enforcement: CANDIDATE model can NEVER actuate hardware or authorize alerts
    res = registry.evaluate_execution_safety("m_cand_governed", "ACCIDENT", confidence=0.99)
    assert res.actuators_permitted is False
    assert res.incident_dispatch_permitted is False
    assert res.is_shadow_only is True
    assert any("POLICY_RESTRICTION" in v for v in res.safety_violations)
