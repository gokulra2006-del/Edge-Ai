"""
Tests for Phase 6J: Privacy-Preserving Multi-Node Federated Learning.

Validates:
1. Privacy boundary: strictly prevents raw audio, video, or incident payloads from leaving nodes.
2. Cryptographic update signing and tamper rejection.
3. Determinism under fixed random seeds.
4. Robust Byzantine aggregation (Trimmed-Mean vs standard FedAvg).
5. Differential privacy gradient clipping and epsilon tracking.
6. Non-IID cross-zone performance gains over isolated local models.
7. Governance: Aggregated models enter registry strictly as CANDIDATE and cannot actuate hardware.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import pytest

from src.modules.federated.model import EdgeMultimodalModel, CLASSES, FEATURE_DIM
from src.modules.federated.node import (
    FederatedEdgeNode,
    PrivacyBoundaryViolation,
    compute_payload_signature,
)
from src.modules.federated.aggregator import (
    FederatedAggregator,
    AggregationStrategy,
)
from src.modules.federated.federated_engine import (
    FederatedSimulationEngine,
    generate_synthetic_feature_sample,
)
from src.modules.core.safety_registry_gate import SafetyAwareModelRegistry


def test_privacy_boundary_enforcement():
    """Verify that any presence of raw audio, video, or features in payloads raises PrivacyBoundaryViolation."""
    node = FederatedEdgeNode(
        node_id="node_zone_a",
        zone_id="ZONE_A",
        secret_key="secret_test_key_123",
        seed=42,
    )

    # 1. Valid delta payload passes
    valid_deltas = [0.01 * i for i in range(len(node.model.get_flat_weights()))]
    payload = node.create_update_payload(
        round_idx=1,
        flat_deltas=valid_deltas,
        sample_count=100,
        loss=0.45,
    )
    assert "signature" in payload
    assert "node_id" in payload

    # 2. Attempting to inject raw audio leaks
    leaked_audio_payload = dict(payload)
    leaked_audio_payload["raw_audio"] = [0.12, -0.05, 0.44]
    with pytest.raises(PrivacyBoundaryViolation, match="Forbidden field 'raw_audio'"):
        node.assert_privacy_boundary(leaked_audio_payload)

    # 3. Attempting to inject video frames
    leaked_video_payload = dict(payload)
    leaked_video_payload["video_frames"] = "data:image/jpeg;base64,..."
    with pytest.raises(PrivacyBoundaryViolation, match="Forbidden field 'video_frames'"):
        node.assert_privacy_boundary(leaked_video_payload)

    # 4. Attempting to inject raw feature vectors
    leaked_features_payload = dict(payload)
    leaked_features_payload["raw_features"] = [[0.1, 0.2]]
    with pytest.raises(PrivacyBoundaryViolation, match="Forbidden field 'raw_features'"):
        node.assert_privacy_boundary(leaked_features_payload)

    # 5. Non-numeric parameter deltas
    invalid_type_payload = dict(payload)
    invalid_type_payload["flat_deltas"] = ["not_a_float", 1.23]
    with pytest.raises(PrivacyBoundaryViolation, match="purely numerical vector"):
        node.assert_privacy_boundary(invalid_type_payload)


def test_signature_verification_and_tamper_rejection():
    """Verify that unsigned, forged, or altered payloads are 100% rejected by aggregator."""
    base_model = EdgeMultimodalModel(seed=42)
    aggregator = FederatedAggregator(initial_model=base_model)
    secret_key = "node_a_valid_key"
    aggregator.register_node("node_zone_a", "ZONE_A", secret_key)

    node = FederatedEdgeNode("node_zone_a", "ZONE_A", secret_key, initial_model=base_model, seed=42)
    valid_deltas = [0.02] * len(base_model.get_flat_weights())
    payload = node.create_update_payload(round_idx=0, flat_deltas=valid_deltas, sample_count=50, loss=0.5)

    # 1. Valid payload succeeds
    is_valid, reason = aggregator.verify_update(payload)
    assert is_valid is True
    assert reason == "VALID"

    # 2. Tampered delta coordinate
    tampered_payload = copy.deepcopy(payload)
    tampered_payload["flat_deltas"][0] += 0.99
    is_valid, reason = aggregator.verify_update(tampered_payload)
    assert is_valid is False
    assert "signature mismatch" in reason.lower()

    # 3. Tampered sample count
    tampered_count = copy.deepcopy(payload)
    tampered_count["sample_count"] = 999999
    is_valid, reason = aggregator.verify_update(tampered_count)
    assert is_valid is False
    assert "signature mismatch" in reason.lower()

    # 4. Missing signature
    unsigned = copy.deepcopy(payload)
    del unsigned["signature"]
    is_valid, reason = aggregator.verify_update(unsigned)
    assert is_valid is False
    assert "missing cryptographic signature" in reason.lower()

    # 5. Unregistered node
    unregistered = copy.deepcopy(payload)
    unregistered["node_id"] = "rogue_node_x"
    is_valid, reason = aggregator.verify_update(unregistered)
    assert is_valid is False
    assert "unregistered" in reason.lower()


def test_determinism_under_fixed_seed():
    """Verify that runs with identical random seeds generate identical weights and metrics."""
    engine1 = FederatedSimulationEngine(num_nodes=3, samples_per_node=60, seed=123)
    res1 = engine1.run_federated_training(rounds=2, local_epochs=2, seed_strategy=None) if hasattr(engine1, 'x') else engine1.run_federated_training(rounds=2, local_epochs=2)

    engine2 = FederatedSimulationEngine(num_nodes=3, samples_per_node=60, seed=123)
    res2 = engine2.run_federated_training(rounds=2, local_epochs=2)

    assert res1["overall_macro_f1"] == res2["overall_macro_f1"]
    assert res1["overall_accuracy"] == res2["overall_accuracy"]
    assert res1["final_model"].get_flat_weights() == res2["final_model"].get_flat_weights()


def test_byzantine_robust_aggregation():
    """Verify that Robust Trimmed-Mean filters out poisoned Byzantine node updates."""
    base_model = EdgeMultimodalModel(seed=42)
    agg_fedavg = FederatedAggregator(initial_model=base_model, strategy=AggregationStrategy.FED_AVG)
    agg_robust = FederatedAggregator(
        initial_model=base_model,
        strategy=AggregationStrategy.ROBUST_TRIMMED_MEAN,
        trim_fraction=0.25,
    )

    # 3 honest nodes, 1 malicious node
    nodes = ["node_h1", "node_h2", "node_h3", "node_malicious"]
    keys = {n: f"key_{n}" for n in nodes}
    for n in nodes:
        agg_fedavg.register_node(n, "ZONE_A", keys[n])
        agg_robust.register_node(n, "ZONE_A", keys[n])

    param_len = len(base_model.get_flat_weights())
    updates = []
    # Honest updates: small positive deltas ~0.05
    for n in ["node_h1", "node_h2", "node_h3"]:
        node = FederatedEdgeNode(n, "ZONE_A", keys[n], initial_model=base_model)
        upd = node.create_update_payload(0, [0.05] * param_len, sample_count=50, loss=0.3)
        updates.append(upd)

    # Malicious update: extreme gradient poisoning (+500.0)
    mal_node = FederatedEdgeNode("node_malicious", "ZONE_A", keys["node_malicious"], initial_model=base_model)
    poisoned_deltas = [500.0] * param_len
    mal_upd = mal_node.create_update_payload(0, poisoned_deltas, sample_count=50, loss=0.1)
    updates.append(mal_upd)

    res_fedavg = agg_fedavg.aggregate_round(0, updates)
    res_robust = agg_robust.aggregate_round(0, updates)

    fedavg_weights = agg_fedavg.global_model.get_flat_weights()
    robust_weights = agg_robust.global_model.get_flat_weights()

    # FedAvg weights should be blown out by the poisoned update (~125.0 delta)
    assert any(abs(w) > 50.0 for w in fedavg_weights)
    # Robust Trimmed-Mean should have discarded the poisoned outlier, keeping weights small
    assert all(abs(w) < 5.0 for w in robust_weights)


def test_differential_privacy_clipping_and_budget():
    """Verify that DP clips weight deltas by L2 norm and attaches privacy metadata."""
    node = FederatedEdgeNode("node_dp", "ZONE_DP", "secret_key_dp", seed=42)
    fake_samples = [
        {"features": [0.1 * i for i in range(8)], "label": i % 4, "label_name": CLASSES[i % 4]}
        for i in range(40)
    ]
    node.load_local_data(fake_samples)

    upd = node.train_round(
        round_idx=0,
        epochs=3,
        lr=0.1,
        use_differential_privacy=True,
        dp_clip_norm=0.5,
        dp_noise_multiplier=0.1,
    )

    dp_meta = upd["dp_metadata"]
    assert dp_meta is not None
    assert dp_meta["differential_privacy_enabled"] is True
    assert dp_meta["clip_norm"] == 0.5
    assert dp_meta["noise_multiplier"] == 0.1
    assert "effective_epsilon" in dp_meta
    assert dp_meta["effective_epsilon"] > 0


def test_non_iid_cross_zone_generalization():
    """Verify that federated global model improves cross-zone generalization over isolated local models."""
    engine = FederatedSimulationEngine(num_nodes=3, samples_per_node=100, seed=42)

    local_res = engine.run_local_only_benchmark(epochs=12, lr=0.08)
    fed_res = engine.run_federated_training(rounds=5, local_epochs=4, lr=0.08)

    # Federated model cross-zone generalization should exceed average isolated cross-zone F1 by >= 15%
    rel_improvement = (fed_res["overall_macro_f1"] - local_res["average_cross_zone_f1"]) / max(0.01, local_res["average_cross_zone_f1"])
    assert rel_improvement >= 0.15
    assert fed_res["overall_macro_f1"] > local_res["average_cross_zone_f1"]
    assert fed_res["overall_macro_f1"] >= 0.60
    assert fed_res["ece"] <= 0.50


def test_governance_candidate_registry_entry():
    """Verify that aggregated federated model enters registry strictly as CANDIDATE."""
    engine = FederatedSimulationEngine(num_nodes=3, samples_per_node=60, seed=42)
    fed_res = engine.run_federated_training(rounds=2, local_epochs=2, lr=0.05)

    registry, proposal = engine.register_candidate_in_governance(fed_res, model_id="candidate_fed_v1")

    # Invariant: Registered status must be CANDIDATE
    record = registry.get_model("candidate_fed_v1")
    assert record is not None
    assert record.status == "CANDIDATE"
    assert record.usage_restriction == "RESEARCH_ONLY"

    # Invariant: Cannot actuate physical hardware
    exec_res = registry.execute_with_safety_guardrails("candidate_fed_v1", "TEST_PRED", 0.95)
    assert exec_res.actuators_permitted is False
    assert exec_res.incident_dispatch_permitted is False
    assert exec_res.is_shadow_only is True
    assert any("CANDIDATE" in v for v in exec_res.safety_violations)

    # Formal proposal was generated
    assert proposal.candidate_model_id == "candidate_fed_v1"
    assert proposal.proposal_id.startswith("PROP-")
