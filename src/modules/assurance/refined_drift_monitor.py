"""
Module: Edge OOD & Model Drift Monitoring Refinements.
=====================================================
Implements multi-scale dual-window drift detection (fast vs slow windows)
with exponential moving average (EMA) smoothing and automated assurance
level degradation recommendations.

Research Hypothesis:
Dual-scale drift estimation (combining an agile 20-sample window for immediate
sensor corruptions and an EMA-smoothed 100-sample window for gradual covariate shift)
suppresses spurious drift false alarms by >40% on small batches while maintaining
sub-5-second detection latency for genuine camera/audio distribution changes.

Primary Metrics:
1. False Alarm Suppression Rate: Zero false DRIFT_DETECTED triggers on stationary distribution.
2. Shift Detection Latency: Fast window detects synthetic distribution shock within 20 samples.
3. Assurance Level Degradation: Deterministically flags DEGRADED recommendation on sustained drift.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple

from src.modules.assurance.drift_monitor import compute_histogram, compute_psi


@dataclass
class DriftRefinementResult:
    model_id: str
    status: str  # STABLE, WATCH, DRIFT_DETECTED
    psi_instantaneous: float
    psi_ema: float
    fast_window_samples: int
    slow_window_samples: int
    ood_rate: float
    recommended_assurance: str  # FULL, DEGRADED, REVIEW_REQUIRED
    reasons: List[str]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "status": self.status,
            "psi_instantaneous": round(self.psi_instantaneous, 4),
            "psi_ema": round(self.psi_ema, 4),
            "fast_window_samples": self.fast_window_samples,
            "slow_window_samples": self.slow_window_samples,
            "ood_rate": round(self.ood_rate, 4),
            "recommended_assurance": self.recommended_assurance,
            "reasons": self.reasons,
            "timestamp": self.timestamp,
        }


class RefinedEdgeDriftMonitor:
    """
    Advanced multi-scale edge model drift monitor.
    Maintains fast-window and slow-window queues and applies EMA smoothing
    to eliminate edge telemetry noise.
    """

    def __init__(
        self,
        model_id: str,
        baseline_histogram: List[int],
        fast_window_size: int = 20,
        slow_window_size: int = 100,
        ema_alpha: float = 0.25,
        psi_watch: float = 0.10,
        psi_drift: float = 0.25,
    ):
        self.model_id = model_id
        self.baseline_histogram = baseline_histogram
        self.fast_window_size = fast_window_size
        self.slow_window_size = slow_window_size
        self.ema_alpha = ema_alpha
        self.psi_watch = psi_watch
        self.psi_drift = psi_drift

        self.fast_confidence_samples: List[float] = []
        self.slow_confidence_samples: List[float] = []
        self.ood_flags: List[bool] = []
        self.current_ema_psi: float = 0.0

    def ingest_prediction(self, confidence: float, is_ood: bool = False) -> None:
        """Stream an incoming edge prediction into the multi-scale monitoring buffers."""
        conf = max(0.0, min(1.0, float(confidence)))
        self.fast_confidence_samples.append(conf)
        self.slow_confidence_samples.append(conf)
        self.ood_flags.append(is_ood)

        if len(self.fast_confidence_samples) > self.fast_window_size:
            self.fast_confidence_samples.pop(0)
        if len(self.slow_confidence_samples) > self.slow_window_size:
            self.slow_confidence_samples.pop(0)
        if len(self.ood_flags) > self.slow_window_size:
            self.ood_flags.pop(0)

    def evaluate_drift(self) -> DriftRefinementResult:
        """
        Calculates dual-scale PSI metrics, EMA filtering, and assurance recommendation.
        """
        bins = len(self.baseline_histogram)

        # Minimum sample check
        if len(self.fast_confidence_samples) < 5:
            return DriftRefinementResult(
                model_id=self.model_id,
                status="STABLE",
                psi_instantaneous=0.0,
                psi_ema=self.current_ema_psi,
                fast_window_samples=len(self.fast_confidence_samples),
                slow_window_samples=len(self.slow_confidence_samples),
                ood_rate=0.0,
                recommended_assurance="FULL",
                reasons=["INSUFFICIENT_SAMPLES"],
            )

        # 1. Fast window histogram & instantaneous PSI
        fast_hist = compute_histogram(self.fast_confidence_samples, bins=bins)
        psi_fast = compute_psi(fast_hist, self.baseline_histogram)

        # 2. Slow window histogram & slow PSI
        slow_hist = compute_histogram(self.slow_confidence_samples, bins=bins)
        psi_slow = compute_psi(slow_hist, self.baseline_histogram)

        # 3. Update EMA of PSI (combines fast responsiveness with slow stability)
        if self.current_ema_psi == 0.0:
            self.current_ema_psi = psi_slow
        else:
            self.current_ema_psi = (self.ema_alpha * psi_fast) + ((1.0 - self.ema_alpha) * self.current_ema_psi)

        # 4. OOD rate computation
        ood_count = sum(1 for o in self.ood_flags if o)
        ood_rate = ood_count / max(1, len(self.ood_flags))

        # 5. Determine refined status & reasons
        reasons: List[str] = []
        status = "STABLE"
        recommended_assurance = "FULL"

        if self.current_ema_psi >= self.psi_drift or psi_fast >= (self.psi_drift * 1.5):
            status = "DRIFT_DETECTED"
            recommended_assurance = "DEGRADED"
            reasons.append(f"HIGH_PSI_DRIFT (EMA={self.current_ema_psi:.3f}, Fast={psi_fast:.3f})")
        elif self.current_ema_psi >= self.psi_watch or psi_fast >= self.psi_watch:
            status = "WATCH"
            recommended_assurance = "REVIEW_REQUIRED"
            reasons.append(f"MODERATE_PSI_WATCH (EMA={self.current_ema_psi:.3f})")

        if ood_rate >= 0.20:
            if status == "STABLE":
                status = "WATCH"
                recommended_assurance = "REVIEW_REQUIRED"
            reasons.append(f"ELEVATED_OOD_RATE ({ood_rate*100:.1f}%)")

        return DriftRefinementResult(
            model_id=self.model_id,
            status=status,
            psi_instantaneous=psi_fast,
            psi_ema=self.current_ema_psi,
            fast_window_samples=len(self.fast_confidence_samples),
            slow_window_samples=len(self.slow_confidence_samples),
            ood_rate=ood_rate,
            recommended_assurance=recommended_assurance,
            reasons=reasons,
        )
