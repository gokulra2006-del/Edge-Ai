"""
Multimodal edge classification model for federated training and inference.
"""

from __future__ import annotations

import copy
import math
import random
from typing import Any, Dict, List, Sequence, Tuple

CLASSES: List[str] = [
    "NORMAL",
    "TRAFFIC_COLLISION",
    "FIRE_HAZARD",
    "VIOLENCE_PANIC",
]
NUM_CLASSES = len(CLASSES)
FEATURE_DIM = 8

FEATURE_NAMES: List[str] = [
    "visual_motion_energy",
    "visual_crowd_density",
    "acoustic_rms_energy",
    "acoustic_scream_frequency",
    "imu_impact_jolt",
    "environmental_gas_index",
    "cross_sensor_agreement",
    "temporal_window_stability",
]


class EdgeMultimodalModel:
    """
    Multimodal softmax classifier for edge emergency detection.
    Supports deterministic initialization, SGD training, weight export/import,
    and differential privacy noise addition.
    """

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.num_classes = NUM_CLASSES
        self.feature_dim = FEATURE_DIM
        self.classes = list(CLASSES)

        rng = random.Random(seed)
        # Xavier/He initialization for small linear model
        limit = math.sqrt(6.0 / (FEATURE_DIM + NUM_CLASSES))
        self.weights: List[List[float]] = [
            [rng.uniform(-limit, limit) for _ in range(FEATURE_DIM)]
            for _ in range(NUM_CLASSES)
        ]
        self.biases: List[float] = [0.0 for _ in range(NUM_CLASSES)]

    def forward_logits(self, x: Sequence[float]) -> List[float]:
        """Computes linear logits z_k = W_k · x + b_k."""
        logits = []
        for k in range(self.num_classes):
            dot = sum(w * xi for w, xi in zip(self.weights[k], x))
            logits.append(dot + self.biases[k])
        return logits

    def predict_proba(self, x: Sequence[float]) -> List[float]:
        """Computes numerically stable softmax probabilities."""
        logits = self.forward_logits(x)
        max_l = max(logits)
        exp_logits = [math.exp(l - max_l) for l in logits]
        sum_exp = sum(exp_logits)
        if sum_exp == 0.0:
            return [1.0 / self.num_classes] * self.num_classes
        return [e / sum_exp for e in exp_logits]

    def predict(self, x: Sequence[float]) -> str:
        """Returns the highest probability class label."""
        probs = self.predict_proba(x)
        best_idx = max(range(self.num_classes), key=lambda i: probs[i])
        return self.classes[best_idx]

    def compute_loss(self, X: Sequence[Sequence[float]], y: Sequence[int], l2_reg: float = 0.001) -> float:
        """Categorical cross-entropy loss with L2 regularization."""
        if not X:
            return 0.0
        total_loss = 0.0
        for xi, yi in zip(X, y):
            probs = self.predict_proba(xi)
            p_true = max(1e-12, probs[yi])
            total_loss -= math.log(p_true)
        avg_loss = total_loss / len(X)

        # L2 penalty
        l2_penalty = 0.5 * l2_reg * sum(w * w for row in self.weights for w in row)
        return avg_loss + l2_penalty

    def compute_gradients(
        self,
        X_batch: Sequence[Sequence[float]],
        y_batch: Sequence[int],
        l2_reg: float = 0.001,
    ) -> Tuple[List[List[float]], List[float]]:
        """Computes average gradients of cross-entropy loss w.r.t weights and biases."""
        grad_w = [[0.0] * self.feature_dim for _ in range(self.num_classes)]
        grad_b = [0.0] * self.num_classes
        batch_size = len(X_batch)
        if batch_size == 0:
            return grad_w, grad_b

        for xi, yi in zip(X_batch, y_batch):
            probs = self.predict_proba(xi)
            for k in range(self.num_classes):
                # Gradient of CE w.r.t logits: p_k - 1(y == k)
                err = probs[k] - (1.0 if k == yi else 0.0)
                grad_b[k] += err
                for j in range(self.feature_dim):
                    grad_w[k][j] += err * xi[j]

        # Average and apply L2 regularization
        inv_n = 1.0 / batch_size
        for k in range(self.num_classes):
            grad_b[k] *= inv_n
            for j in range(self.feature_dim):
                grad_w[k][j] = (grad_w[k][j] * inv_n) + (l2_reg * self.weights[k][j])

        return grad_w, grad_b

    def train_sgd(
        self,
        X: Sequence[Sequence[float]],
        y: Sequence[int],
        epochs: int = 5,
        lr: float = 0.05,
        batch_size: int = 16,
        l2_reg: float = 0.001,
        seed: int = 42,
    ) -> float:
        """Runs local Mini-batch Stochastic Gradient Descent."""
        n = len(X)
        if n == 0:
            return 0.0

        indices = list(range(n))
        rng = random.Random(seed)

        for _ in range(epochs):
            rng.shuffle(indices)
            for start_idx in range(0, n, batch_size):
                batch_indices = indices[start_idx : start_idx + batch_size]
                X_batch = [X[i] for i in batch_indices]
                y_batch = [y[i] for i in batch_indices]

                grad_w, grad_b = self.compute_gradients(X_batch, y_batch, l2_reg=l2_reg)

                # Gradient descent step
                for k in range(self.num_classes):
                    self.biases[k] -= lr * grad_b[k]
                    for j in range(self.feature_dim):
                        self.weights[k][j] -= lr * grad_w[k][j]

        return self.compute_loss(X, y, l2_reg=l2_reg)

    def get_weights(self) -> Dict[str, Any]:
        """Returns deep copy of current parameters."""
        return {
            "weights": [list(row) for row in self.weights],
            "biases": list(self.biases),
            "feature_dim": self.feature_dim,
            "num_classes": self.num_classes,
        }

    def set_weights(self, weights_dict: Dict[str, Any]) -> None:
        """Loads weights from dictionary."""
        self.weights = [list(row) for row in weights_dict["weights"]]
        self.biases = list(weights_dict["biases"])

    def get_flat_weights(self) -> List[float]:
        """Flattens weights and biases into a 1D vector."""
        flat = []
        for row in self.weights:
            flat.extend(row)
        flat.extend(self.biases)
        return flat

    def set_flat_weights(self, flat: Sequence[float]) -> None:
        """Unflattens a 1D vector into weights and biases."""
        expected_len = (self.num_classes * self.feature_dim) + self.num_classes
        if len(flat) != expected_len:
            raise ValueError(f"Expected flat weight vector of length {expected_len}, got {len(flat)}")

        idx = 0
        for k in range(self.num_classes):
            for j in range(self.feature_dim):
                self.weights[k][j] = float(flat[idx])
                idx += 1
        for k in range(self.num_classes):
            self.biases[k] = float(flat[idx])
            idx += 1

    def clone(self) -> EdgeMultimodalModel:
        """Creates an identical replica of this model."""
        replica = EdgeMultimodalModel(seed=self.seed)
        replica.set_weights(self.get_weights())
        return replica
