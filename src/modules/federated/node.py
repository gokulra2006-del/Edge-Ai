"""
Federated edge client node with local training, differential privacy,
cryptographic signing, and strict privacy boundary validation.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.modules.federated.model import EdgeMultimodalModel, CLASSES


class PrivacyBoundaryViolation(Exception):
    """Raised when an update payload violates the edge privacy boundary."""


FORBIDDEN_PAYLOAD_KEYS = {
    "audio", "video", "raw_audio", "raw_video", "image", "frames",
    "waveform", "raw_data", "features", "ground_truth", "dataset",
    "samples", "incident_id", "incident_notes", "raw_sensor_stream"
}


def canonical_json(data: Dict[str, Any]) -> str:
    """Serializes dictionary to deterministic JSON string for signing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def compute_payload_signature(secret_key: str, payload_without_sig: Dict[str, Any]) -> str:
    """Computes HMAC-SHA256 signature for the model update payload."""
    msg = canonical_json(payload_without_sig).encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()


class FederatedEdgeNode:
    """
    Simulated physical edge node located in a distinct municipal zone.
    Executes local training and packages tamper-evident parameter updates.
    """

    def __init__(
        self,
        node_id: str,
        zone_id: str,
        secret_key: str,
        initial_model: Optional[EdgeMultimodalModel] = None,
        seed: int = 42,
    ):
        self.node_id = node_id
        self.zone_id = zone_id
        self.secret_key = secret_key
        self.seed = seed
        self.model = initial_model.clone() if initial_model else EdgeMultimodalModel(seed=seed)

        # Local private data strictly isolated inside node
        self._local_samples: List[Dict[str, Any]] = []

    def load_local_data(self, samples: Sequence[Dict[str, Any]]) -> None:
        """Loads private zone dataset into the edge node memory."""
        self._local_samples = [dict(s) for s in samples]

    @property
    def sample_count(self) -> int:
        return len(self._local_samples)

    def receive_global_model(self, global_weights: Dict[str, Any]) -> None:
        """Updates node local model with global parameters broadcast by aggregator."""
        self.model.set_weights(global_weights)

    def train_round(
        self,
        round_idx: int,
        epochs: int = 5,
        lr: float = 0.05,
        batch_size: int = 16,
        l2_reg: float = 0.001,
        use_differential_privacy: bool = False,
        dp_clip_norm: float = 1.0,
        dp_noise_multiplier: float = 0.1,
        dp_delta: float = 1e-4,
    ) -> Dict[str, Any]:
        """
        Executes one local training round:
        1. Records pre-training base weights.
        2. Fits model on local private zone data via SGD.
        3. Computes parameter delta vector.
        4. Optionally clips and perturbs delta with DP Gaussian noise.
        5. Packages and cryptographically signs payload.
        """
        if not self._local_samples:
            raise ValueError(f"Node {self.node_id} has no training data.")

        initial_flat = self.model.get_flat_weights()
        X = [s["features"] for s in self._local_samples]
        y = [s["label"] for s in self._local_samples]

        # Local training
        seed_round = self.seed + (round_idx * 1000)
        final_loss = self.model.train_sgd(
            X, y,
            epochs=epochs,
            lr=lr,
            batch_size=batch_size,
            l2_reg=l2_reg,
            seed=seed_round,
        )

        trained_flat = self.model.get_flat_weights()
        deltas = [w_new - w_old for w_new, w_old in zip(trained_flat, initial_flat)]

        dp_metadata = None
        if use_differential_privacy:
            # 1. Compute L2 norm of weight delta
            delta_norm = math.sqrt(sum(d * d for d in deltas))
            # 2. Clip delta by threshold C
            clip_factor = min(1.0, dp_clip_norm / max(1e-12, delta_norm))
            clipped_deltas = [d * clip_factor for d in deltas]

            # 3. Add calibrated Gaussian noise N(0, (sigma * C)^2)
            noise_std = dp_noise_multiplier * dp_clip_norm
            rng = random.Random(seed_round + 777)
            noisy_deltas = [
                d + rng.gauss(0.0, noise_std)
                for d in clipped_deltas
            ]
            deltas = noisy_deltas

            # Effective epsilon under analytic Gaussian mechanism
            # eps = (clip_norm * sqrt(2 * ln(1.25 / delta))) / (noise_std)
            # which simplifies to sqrt(2 * ln(1.25 / delta)) / dp_noise_multiplier
            eps = round(math.sqrt(2.0 * math.log(1.25 / dp_delta)) / max(1e-6, dp_noise_multiplier), 4)

            dp_metadata = {
                "differential_privacy_enabled": True,
                "clip_norm": dp_clip_norm,
                "noise_multiplier": dp_noise_multiplier,
                "target_delta": dp_delta,
                "effective_epsilon": eps,
                "pre_clip_norm": round(delta_norm, 5),
            }

            # Update model with privatized weights
            privatized_flat = [w_old + d for w_old, d in zip(initial_flat, deltas)]
            self.model.set_flat_weights(privatized_flat)

        # Assemble and sign payload
        payload = self.create_update_payload(
            round_idx=round_idx,
            flat_deltas=deltas,
            sample_count=len(self._local_samples),
            loss=final_loss,
            dp_metadata=dp_metadata,
        )
        return payload

    def create_update_payload(
        self,
        round_idx: int,
        flat_deltas: List[float],
        sample_count: int,
        loss: float,
        dp_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Creates, asserts privacy boundaries, and cryptographically signs model update payload.
        """
        payload = {
            "node_id": self.node_id,
            "zone_id": self.zone_id,
            "round_idx": round_idx,
            "sample_count": sample_count,
            "loss": round(loss, 6),
            "flat_deltas": [round(float(d), 6) for d in flat_deltas],
            "dp_metadata": dp_metadata,
        }

        # Privacy boundary check
        self.assert_privacy_boundary(payload)

        # Cryptographic signing
        sig = compute_payload_signature(self.secret_key, payload)
        payload["signature"] = sig
        return payload

    @staticmethod
    def assert_privacy_boundary(payload: Dict[str, Any]) -> None:
        """
        Strictly enforces that no raw data, waveforms, video frames, or incident records
        leak through the federated client-server boundary.
        """
        for key in payload.keys():
            k_lower = key.lower()
            for forbidden in FORBIDDEN_PAYLOAD_KEYS:
                if forbidden in k_lower:
                    raise PrivacyBoundaryViolation(
                        f"Privacy boundary violation: Forbidden field '{key}' detected in model update payload."
                    )

        # Assert flat_deltas contains strictly numeric values
        deltas = payload.get("flat_deltas", [])
        if not isinstance(deltas, list) or not all(isinstance(v, (int, float)) for v in deltas):
            raise PrivacyBoundaryViolation(
                "Privacy boundary violation: 'flat_deltas' must be a purely numerical vector."
            )
