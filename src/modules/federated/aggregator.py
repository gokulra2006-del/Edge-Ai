"""
Federated aggregation server supporting FedAvg, Byzantine-robust trimmed mean,
cryptographic verification, and communication cost accounting.
"""

from __future__ import annotations

import copy
from enum import Enum
import json
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.modules.federated.model import EdgeMultimodalModel
from src.modules.federated.node import (
    canonical_json,
    compute_payload_signature,
    PrivacyBoundaryViolation,
)


class AggregationStrategy(str, Enum):
    FED_AVG = "FED_AVG"
    ROBUST_TRIMMED_MEAN = "ROBUST_TRIMMED_MEAN"
    COORDINATE_MEDIAN = "COORDINATE_MEDIAN"


class FederatedAggregator:
    """
    Central or orchestrating aggregator for municipal edge nodes.
    Authenticates node updates, enforces tamper-evident cryptography,
    measures wire communication overhead, and merges model updates.
    """

    def __init__(
        self,
        initial_model: EdgeMultimodalModel,
        strategy: AggregationStrategy = AggregationStrategy.FED_AVG,
        trim_fraction: float = 0.2,
    ):
        self.global_model = initial_model.clone()
        self.strategy = strategy
        self.trim_fraction = trim_fraction

        # Registered node identities and HMAC secrets
        self._registered_nodes: Dict[str, Dict[str, str]] = {}

        # Round tracking
        self.round_history: List[Dict[str, Any]] = []

    def register_node(self, node_id: str, zone_id: str, secret_key: str) -> None:
        """Enrolls an edge node into the federated network."""
        self._registered_nodes[node_id] = {
            "zone_id": zone_id,
            "secret_key": secret_key,
        }

    def verify_update(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Cryptographically verifies the authenticity and integrity of a model update.
        Rejects unsigned, forged, or altered payloads.
        """
        if not isinstance(payload, dict):
            return False, "Payload is not a valid dictionary"

        node_id = payload.get("node_id")
        if not node_id or node_id not in self._registered_nodes:
            return False, f"Unregistered or missing node_id: '{node_id}'"

        signature = payload.get("signature")
        if not signature:
            return False, "Missing cryptographic signature"

        # Reconstruct unsigned payload
        payload_copy = dict(payload)
        del payload_copy["signature"]

        secret_key = self._registered_nodes[node_id]["secret_key"]
        expected_sig = compute_payload_signature(secret_key, payload_copy)

        if not signature == expected_sig:
            return False, "Cryptographic signature mismatch; payload was altered or forged"

        deltas = payload.get("flat_deltas")
        expected_len = len(self.global_model.get_flat_weights())
        if not isinstance(deltas, list) or len(deltas) != expected_len:
            return False, f"Invalid delta length: expected {expected_len}, got {len(deltas) if isinstance(deltas, list) else 0}"

        return True, "VALID"

    def aggregate_round(
        self,
        round_idx: int,
        updates: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Processes node updates:
        1. Authenticates all incoming updates; filters out invalid or tampered submissions.
        2. Measures wire communication bytes (inbound upload + outbound broadcast).
        3. Aggregates parameter deltas using chosen strategy.
        4. Updates the global model weights.
        """
        t0 = time.perf_counter()

        valid_updates = []
        rejected_updates = []
        upload_bytes = 0

        # 1. Inbound validation and wire-size calculation
        for upd in updates:
            upd_bytes = len(canonical_json(upd).encode("utf-8"))
            upload_bytes += upd_bytes

            is_valid, reason = self.verify_update(upd)
            if is_valid:
                valid_updates.append(upd)
            else:
                rejected_updates.append({
                    "node_id": upd.get("node_id", "UNKNOWN"),
                    "reason": reason,
                })

        if not valid_updates:
            raise ValueError(f"Round {round_idx} failed: No valid node updates received.")

        # 2. Aggregation
        current_flat = self.global_model.get_flat_weights()
        num_params = len(current_flat)

        if self.strategy == AggregationStrategy.FED_AVG:
            agg_delta = self._aggregate_fed_avg(valid_updates, num_params)
        elif self.strategy == AggregationStrategy.ROBUST_TRIMMED_MEAN:
            agg_delta = self._aggregate_trimmed_mean(valid_updates, num_params)
        elif self.strategy == AggregationStrategy.COORDINATE_MEDIAN:
            agg_delta = self._aggregate_coordinate_median(valid_updates, num_params)
        else:
            agg_delta = self._aggregate_fed_avg(valid_updates, num_params)

        # 3. Apply aggregated delta to global model
        updated_flat = [w + d for w, d in zip(current_flat, agg_delta)]
        self.global_model.set_flat_weights(updated_flat)

        aggregation_latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)

        # 4. Outbound broadcast wire size (global model payload to all participating nodes)
        broadcast_payload = {
            "round_idx": round_idx,
            "weights": self.global_model.get_weights(),
        }
        single_broadcast_bytes = len(canonical_json(broadcast_payload).encode("utf-8"))
        total_broadcast_bytes = single_broadcast_bytes * len(valid_updates)

        total_bytes = upload_bytes + total_broadcast_bytes

        round_summary = {
            "round_idx": round_idx,
            "strategy": self.strategy.value,
            "participating_nodes": [u["node_id"] for u in valid_updates],
            "rejected_nodes": rejected_updates,
            "participating_count": len(valid_updates),
            "rejected_count": len(rejected_updates),
            "upload_bytes": upload_bytes,
            "broadcast_bytes": total_broadcast_bytes,
            "total_round_bytes": total_bytes,
            "aggregation_latency_ms": aggregation_latency_ms,
            "global_weights": self.global_model.get_weights(),
        }

        self.round_history.append(round_summary)
        return round_summary

    def _aggregate_fed_avg(self, updates: List[Dict[str, Any]], num_params: int) -> List[float]:
        """FedAvg: Weighted average of deltas proportional to local dataset size."""
        total_samples = sum(u["sample_count"] for u in updates)
        agg_delta = [0.0] * num_params

        for u in updates:
            weight = u["sample_count"] / max(1, total_samples)
            deltas = u["flat_deltas"]
            for j in range(num_params):
                agg_delta[j] += weight * deltas[j]

        return agg_delta

    def _aggregate_trimmed_mean(self, updates: List[Dict[str, Any]], num_params: int) -> List[float]:
        """Coordinate-wise Trimmed Mean: Discards extreme outliers for Byzantine robustness."""
        k = len(updates)
        trim_count = max(0, int(k * self.trim_fraction))

        # If too few nodes to trim symmetrically on both ends, fall back to FedAvg
        if (2 * trim_count) >= k:
            return self._aggregate_fed_avg(updates, num_params)

        agg_delta = [0.0] * num_params
        for j in range(num_params):
            vals = sorted([u["flat_deltas"][j] for u in updates])
            kept = vals[trim_count : k - trim_count]
            agg_delta[j] = sum(kept) / len(kept)

        return agg_delta

    def _aggregate_coordinate_median(self, updates: List[Dict[str, Any]], num_params: int) -> List[float]:
        """Coordinate-wise Median for extreme outlier suppression."""
        k = len(updates)
        agg_delta = [0.0] * num_params

        for j in range(num_params):
            vals = sorted([u["flat_deltas"][j] for u in updates])
            mid = k // 2
            if k % 2 == 1:
                agg_delta[j] = vals[mid]
            else:
                agg_delta[j] = (vals[mid - 1] + vals[mid]) / 2.0

        return agg_delta
