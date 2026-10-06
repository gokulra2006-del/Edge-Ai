#!/usr/bin/env python3
"""
scripts/run_federated_simulation.py
Simulates privacy-preserving multi-node federated learning across non-IID urban zones.
Compares Local-Only vs Centralized vs FedAvg vs Robust Trimmed-Mean vs Differential Privacy.
Outputs results/federated_learning_results.json tagged strictly as SYNTHETIC.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.pi.common import get_git_hash
from src.modules.federated.federated_engine import FederatedSimulationEngine
from src.modules.federated.aggregator import AggregationStrategy


def run_federated_experiment(
    num_nodes: int = 3,
    samples_per_node: int = 150,
    rounds: int = 6,
    seed: int = 42,
    output_path: Path | str = REPO_ROOT / "results" / "federated_learning_results.json",
) -> dict:
    print("=================================================================")
    print("Sentinel-AI: Federated Multi-Node Learning Simulation (Phase 6J)")
    print(f"Data Tag: SYNTHETIC (Simulated non-IID zones on single host)")
    print(f"Nodes: {num_nodes} | Samples/Node: {samples_per_node} | Rounds: {rounds} | Seed: {seed}")
    print("=================================================================\n")

    engine = FederatedSimulationEngine(
        num_nodes=num_nodes,
        samples_per_node=samples_per_node,
        seed=seed,
    )

    # 1. Local-Only Benchmark
    print("[1/5] Running Local-Only Isolated Baseline...")
    local_res = engine.run_local_only_benchmark(epochs=15, lr=0.05)
    print(f"      Avg Native F1: {local_res['average_overall_macro_f1']} | Avg Cross-Zone F1: {local_res['average_cross_zone_f1']}\n")

    # 2. Centralized Benchmark (Privacy-Violating Baseline)
    print("[2/5] Running Hypothetical Centralized Pooled Baseline...")
    cent_res = engine.run_centralized_baseline(epochs=15, lr=0.05)
    print(f"      Centralized Macro-F1: {cent_res['overall_macro_f1']} | ECE: {cent_res['ece']}\n")

    # 3. Federated Baseline (Standard FedAvg)
    print("[3/5] Running Federated Learning (FedAvg)...")
    fedavg_res = engine.run_federated_training(
        rounds=rounds,
        local_epochs=3,
        lr=0.05,
        strategy=AggregationStrategy.FED_AVG,
    )
    print(f"      FedAvg Macro-F1: {fedavg_res['overall_macro_f1']} | ECE: {fedavg_res['ece']}")
    print(f"      Communication: {fedavg_res['communication']['avg_bytes_per_round']} bytes/round\n")

    # 4. Federated Robust Trimmed-Mean
    print("[4/5] Running Byzantine-Robust Federated Learning (Trimmed-Mean)...")
    robust_res = engine.run_federated_training(
        rounds=rounds,
        local_epochs=3,
        lr=0.05,
        strategy=AggregationStrategy.ROBUST_TRIMMED_MEAN,
    )
    print(f"      Robust FedAvg Macro-F1: {robust_res['overall_macro_f1']} | ECE: {robust_res['ece']}\n")

    # 5. Federated with Differential Privacy (DP)
    print("[5/5] Running Differential Privacy Federated Learning (DP-FedAvg)...")
    dp_res = engine.run_federated_training(
        rounds=rounds,
        local_epochs=3,
        lr=0.05,
        strategy=AggregationStrategy.FED_AVG,
        use_differential_privacy=True,
        dp_clip_norm=1.0,
        dp_noise_multiplier=0.05,
    )
    print(f"      DP-FedAvg Macro-F1: {dp_res['overall_macro_f1']} | ECE: {dp_res['ece']}\n")

    # Governance check: Register as CANDIDATE
    print("[Governance] Registering Federated Global Model in Model Registry...")
    registry, proposal = engine.register_candidate_in_governance(fedavg_res)
    candidate_id = "sentinel_federated_v1"
    exec_result = registry.execute_with_safety_guardrails(candidate_id, "TEST", 0.9)
    print(f"      Candidate Status: {registry.get_model(candidate_id).status}")
    print(f"      Actuators Permitted: {exec_result.actuators_permitted}")
    print(f"      Shadow Only: {exec_result.is_shadow_only}\n")

    # Assemble comprehensive results record
    timestamp_now = datetime.now(timezone.utc).isoformat()
    git_hash = get_git_hash()

    results_data = {
        "benchmark": "federated_multi_node_simulation",
        "data_tag": "SYNTHETIC",
        "timestamp_utc": timestamp_now,
        "git_hash": git_hash,
        "seed": seed,
        "parameters": {
            "num_nodes": num_nodes,
            "samples_per_node": samples_per_node,
            "rounds": rounds,
            "zones": [cfg["zone_id"] for cfg in engine.zone_configs],
        },
        "limitations": [
            "Simulated multi-node environment on a single workstation.",
            "Does not measure physical wide-area network latency, cellular jitter, or node hardware throttling.",
            "All results are strictly tagged SYNTHETIC in accordance with research integrity rules."
        ],
        "baselines": {
            "local_only": {
                "average_overall_macro_f1": local_res["average_overall_macro_f1"],
                "average_cross_zone_f1": local_res["average_cross_zone_f1"],
                "per_zone": local_res["per_node"],
            },
            "centralized_pooled": {
                "macro_f1": cent_res["overall_macro_f1"],
                "accuracy": cent_res["overall_accuracy"],
                "ece": cent_res["ece"],
                "brier_score": cent_res["brier_score"],
                "per_zone_macro_f1": cent_res["per_zone_macro_f1"],
            },
            "fed_avg": {
                "macro_f1": fedavg_res["overall_macro_f1"],
                "accuracy": fedavg_res["overall_accuracy"],
                "ece": fedavg_res["ece"],
                "brier_score": fedavg_res["brier_score"],
                "per_zone_macro_f1": fedavg_res["per_zone_macro_f1"],
                "drift_macro_f1": fedavg_res["drift_macro_f1"],
                "drift_f1_retention_pct": fedavg_res["drift_f1_retention_pct"],
                "communication": fedavg_res["communication"],
            },
            "robust_trimmed_mean": {
                "macro_f1": robust_res["overall_macro_f1"],
                "accuracy": robust_res["overall_accuracy"],
                "ece": robust_res["ece"],
                "brier_score": robust_res["brier_score"],
                "per_zone_macro_f1": robust_res["per_zone_macro_f1"],
            },
            "differential_privacy_fedavg": {
                "macro_f1": dp_res["overall_macro_f1"],
                "accuracy": dp_res["overall_accuracy"],
                "ece": dp_res["ece"],
                "brier_score": dp_res["brier_score"],
                "clip_norm": 1.0,
                "noise_multiplier": 0.05,
            },
        },
        "governance_verification": {
            "candidate_model_id": candidate_id,
            "registry_status": registry.get_model(candidate_id).status,
            "actuators_permitted": exec_result.actuators_permitted,
            "is_shadow_only": exec_result.is_shadow_only,
            "proposal_id": proposal.proposal_id,
        },
    }

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(results_data, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[OK] Simulation completed successfully. Results saved to: {out_p}")
    return results_data


def main():
    parser = argparse.ArgumentParser(description="Sentinel-AI Federated Learning Simulation")
    parser.add_argument("--nodes", type=int, default=3, help="Number of simulated edge nodes")
    parser.add_argument("--samples", type=int, default=150, help="Samples per node")
    parser.add_argument("--rounds", type=int, default=6, help="Federated training rounds")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    parser.add_argument("--output", type=str, default="results/federated_learning_results.json", help="Output JSON path")
    args = parser.parse_args()

    run_federated_experiment(
        num_nodes=args.nodes,
        samples_per_node=args.samples,
        rounds=args.rounds,
        seed=args.seed,
        output_path=Path(args.output),
    )


if __name__ == "__main__":
    main()
