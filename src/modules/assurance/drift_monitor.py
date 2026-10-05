"""Feature 7: Model drift monitoring service and statistical tests."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional

from src.config.governance_config import load_governance_config
from src.config.model_profile import model_profile
from src.modules.database.governed_store import IncidentRepository, IncidentStatus, utc_now
from src.modules.logging.logger import LOGGER


def compute_histogram(values: List[float], bins: int = 10) -> List[int]:
    """Computes fixed-width bin histogram over [0.0, 1.0]."""
    hist = [0] * bins
    for v in values:
        val = max(0.0, min(1.0, float(v)))
        idx = min(int(val * bins), bins - 1)
        hist[idx] += 1
    return hist


def compute_psi(actual_counts: List[int], expected_counts: List[int], epsilon: float = 1e-4) -> float:
    """Computes Population Stability Index (PSI) with smoothing."""
    total_actual = sum(actual_counts)
    total_expected = sum(expected_counts)
    if total_actual == 0 or total_expected == 0:
        return 0.0

    actual_pct = [(c + epsilon) / (total_actual + epsilon * len(actual_counts)) for c in actual_counts]
    expected_pct = [(c + epsilon) / (total_expected + epsilon * len(expected_counts)) for c in expected_counts]

    psi = 0.0
    for a, e in zip(actual_pct, expected_pct):
        psi += (a - e) * math.log(a / e)
    return max(0.0, float(psi))


class ModelDriftMonitor:
    """Evaluates live prediction statistics against baselines without blocking inference."""

    def __init__(self, repository: IncidentRepository, config: Optional[Dict[str, Any]] = None):
        self.repository = repository
        self.root_config = config or self._load_config()
        self.cfg = self.root_config.get("monitoring", {}).get("drift", {})
        self.thresholds = self.cfg.get("thresholds", {
            "psi_watch": 0.1,
            "psi_drift_warning": 0.25,
            "class_prior_shift_warning": 0.3,
            "ood_rate_warning": 0.2,
            "false_alarm_rate_warning": 0.15,
            "disagreement_rate_review": 0.35,
        })
        self.rolling_window = int(self.cfg.get("rolling_window_samples", 50))
        self.min_samples_guard = int(self.cfg.get("minimum_samples_guard", 10))
        self.retention_snapshots = int(self.cfg.get("retention_snapshots", 100))
        self._last_statuses: Dict[str, str] = {}
        self._lock = threading.Lock()

    def _load_config(self) -> Dict[str, Any]:
        cfg_file = Path(__file__).resolve().parents[2] / "config" / "advanced_platform.json"
        try:
            return json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def ensure_default_baselines(self) -> None:
        """Seed default baselines for synthetic or production models if not present."""
        profile = model_profile()
        is_synthetic = bool(profile.get("synthetic"))
        usage_res = "RESEARCH_ONLY" if is_synthetic else "PRODUCTION"
        source = "synthetic" if is_synthetic else "validation_dataset"

        # Baseline uniform-skewed for edge models
        default_hist = [2, 3, 5, 8, 12, 18, 25, 35, 45, 60]
        default_priors = {"crash": 0.2, "fire": 0.2, "ambulance": 0.2, "vehicle": 0.2, "smoke": 0.2}

        for model_id in ["assurance-audio", "assurance-vision", "yolo11n-sentinel", "acoustic-edge"]:
            self.set_baseline(
                model_id=model_id,
                histogram=default_hist,
                ood_rate=0.04,
                class_prior=default_priors,
                false_alarm_rate=0.03,
                source=source,
                sample_count=sum(default_hist),
                usage_restriction=usage_res
            )

    def set_baseline(
        self,
        model_id: str,
        histogram: List[int],
        ood_rate: float,
        class_prior: Dict[str, float],
        false_alarm_rate: float,
        source: str,
        sample_count: int,
        usage_restriction: str | None = None
    ) -> None:
        if usage_restriction is None:
            usage_restriction = "RESEARCH_ONLY" if source == "synthetic" else "PRODUCTION" if source != "unverified" else "UNVERIFIED"

        self.repository.writer.submit(
            lambda db: db.execute(
                """
                INSERT OR REPLACE INTO model_baselines
                (model_id, confidence_histogram_json, ood_rate, class_prior_json, false_alarm_rate, source, sample_count, usage_restriction, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_id,
                    json.dumps(histogram),
                    float(ood_rate),
                    json.dumps(class_prior),
                    float(false_alarm_rate),
                    source,
                    int(sample_count),
                    usage_restriction,
                    utc_now(),
                )
            )
        )

    def get_baseline(self, model_id: str) -> Optional[Dict[str, Any]]:
        rows = self.repository._read("SELECT * FROM model_baselines WHERE model_id=?", (model_id,))
        if not rows:
            return None
        r = dict(rows[0])
        r["confidence_histogram"] = json.loads(r["confidence_histogram_json"])
        r["class_prior"] = json.loads(r["class_prior_json"])
        return r

    def evaluate_model(self, model_id: str) -> Dict[str, Any]:
        """Calculates live stats over rolling window and compares to baseline."""
        baseline = self.get_baseline(model_id)

        # 1. Fetch recent predictions for model_id (or all if model_id is generic)
        if model_id in ("all", "live-fusion"):
            pred_rows = self.repository._read(
                "SELECT id, label, confidence, payload_json FROM predictions ORDER BY id DESC LIMIT ?",
                (self.rolling_window,)
            )
        else:
            pred_rows = self.repository._read(
                "SELECT id, label, confidence, payload_json FROM predictions WHERE model_id=? ORDER BY id DESC LIMIT ?",
                (model_id, self.rolling_window)
            )

        samples = len(pred_rows)
        insufficient_data = samples < self.min_samples_guard

        if not baseline:
            # Baseline missing -> UNVERIFIED / WATCH
            reasons = ["NO_BASELINE_RECORDED"]
            metrics = {"samples": samples}
            status = "WATCH"
            result = {
                "model_id": model_id,
                "status": status,
                "insufficient_data": True,
                "reasons": reasons,
                "metrics": metrics,
                "research_only": True,
                "timestamp": utc_now(),
            }
            self._record_snapshot(model_id, result)
            return result

        if samples == 0:
            result = {
                "model_id": model_id,
                "status": "STABLE",
                "insufficient_data": True,
                "reasons": ["INSUFFICIENT_SAMPLES"],
                "metrics": {"samples": 0},
                "research_only": baseline.get("usage_restriction") == "RESEARCH_ONLY",
                "timestamp": utc_now(),
            }
            self._record_snapshot(model_id, result)
            return result

        confidences = [float(r["confidence"]) for r in pred_rows]
        mean_conf = sum(confidences) / len(confidences)
        live_hist = compute_histogram(confidences, bins=len(baseline["confidence_histogram"]))
        psi_val = compute_psi(live_hist, baseline["confidence_histogram"])

        # Live class priors
        class_counts: Dict[str, int] = {}
        ood_count = 0
        pred_ids = [r["id"] for r in pred_rows]

        for r in pred_rows:
            label = str(r["label"])
            class_counts[label] = class_counts.get(label, 0) + 1
            payload = json.loads(r["payload_json"] or "{}")
            if payload.get("ood_status") in ("UNKNOWN", "REVIEW_REQUIRED") or payload.get("reason_codes"):
                ood_count += 1

        live_priors = {k: v / samples for k, v in class_counts.items()}
        ood_rate = ood_count / samples

        # Operator disagreement from prediction_feedback
        disagreements = 0
        total_feedback = 0
        if pred_ids:
            placeholders = ",".join("?" for _ in pred_ids)
            fb_rows = self.repository._read(
                f"SELECT label FROM prediction_feedback WHERE prediction_id IN ({placeholders})",
                tuple(pred_ids)
            )
            for fb in fb_rows:
                total_feedback += 1
                if fb["label"] == "INCORRECT":
                    disagreements += 1

        disagreement_rate = (disagreements / total_feedback) if total_feedback > 0 else 0.0

        # False alarm rate from incidents
        false_alarms = self.repository._read(
            "SELECT count(*) FROM incidents WHERE status='FALSE_ALARM' AND created_at >= datetime('now', '-1 day')"
        )[0][0]
        total_incidents = max(1, self.repository._read(
            "SELECT count(*) FROM incidents WHERE created_at >= datetime('now', '-1 day')"
        )[0][0])
        live_false_alarm_rate = false_alarms / total_incidents

        # Max class prior shift
        max_prior_shift = 0.0
        for cls, base_pct in baseline["class_prior"].items():
            shift = abs(live_priors.get(cls, 0.0) - base_pct)
            if shift > max_prior_shift:
                max_prior_shift = shift

        metrics = {
            "samples": samples,
            "mean_confidence": round(mean_conf, 4),
            "psi": round(psi_val, 4),
            "max_prior_shift": round(max_prior_shift, 4),
            "ood_rate": round(ood_rate, 4),
            "false_alarm_rate": round(live_false_alarm_rate, 4),
            "disagreement_rate": round(disagreement_rate, 4),
            "feedback_count": total_feedback,
        }

        reasons = []
        if psi_val >= self.thresholds["psi_drift_warning"]:
            reasons.append(f"PSI_HIGH({psi_val:.3f})")
        elif psi_val >= self.thresholds["psi_watch"]:
            reasons.append(f"PSI_WATCH({psi_val:.3f})")

        if max_prior_shift >= self.thresholds["class_prior_shift_warning"]:
            reasons.append(f"CLASS_PRIOR_SHIFT({max_prior_shift:.2f})")
        if ood_rate >= self.thresholds["ood_rate_warning"]:
            reasons.append(f"OOD_RATE_HIGH({ood_rate:.2f})")
        if live_false_alarm_rate >= self.thresholds["false_alarm_rate_warning"]:
            reasons.append(f"FALSE_ALARM_SPIKE({live_false_alarm_rate:.2f})")
        if disagreement_rate >= self.thresholds["disagreement_rate_review"]:
            reasons.append(f"OPERATOR_DISAGREEMENT({disagreement_rate:.2f})")

        # Status assignment
        if disagreement_rate >= self.thresholds["disagreement_rate_review"]:
            status = "REVIEW_REQUIRED"
        elif any("HIGH" in r or "SHIFT" in r or "SPIKE" in r for r in reasons):
            status = "DRIFT_WARNING"
        elif reasons:
            status = "WATCH"
        else:
            status = "STABLE"

        # Minimum sample guard: With too few samples, never go above WATCH!
        if insufficient_data:
            if status in ("DRIFT_WARNING", "REVIEW_REQUIRED"):
                status = "WATCH"
            reasons.append("MINIMUM_SAMPLES_GUARD")

        result = {
            "model_id": model_id,
            "status": status,
            "insufficient_data": insufficient_data,
            "reasons": reasons,
            "metrics": metrics,
            "research_only": baseline.get("usage_restriction") == "RESEARCH_ONLY",
            "timestamp": utc_now(),
        }

        self._record_snapshot(model_id, result)
        return result

    def _record_snapshot(self, model_id: str, result: Dict[str, Any]) -> None:
        status = result["status"]
        reasons_json = json.dumps(result["reasons"])
        metrics_json = json.dumps(result["metrics"])
        samples = result["metrics"].get("samples", 0)
        insufficient = 1 if result["insufficient_data"] else 0
        ts = utc_now()

        # Check for status change
        old_status = self._last_statuses.get(model_id)
        if old_status != status:
            self._last_statuses[model_id] = status
            # Flag model registry if REVIEW_REQUIRED (never auto-disable or swap!)
            if status == "REVIEW_REQUIRED":
                self.repository.writer.submit(
                    lambda db: db.execute(
                        "UPDATE models SET status='REVIEW_REQUIRED' WHERE model_id=?",
                        (model_id,)
                    )
                )

        # Persist snapshot
        self.repository.writer.submit(
            lambda db: db.execute(
                """
                INSERT INTO drift_snapshots
                (model_id, timestamp, status, reasons_json, metrics_json, sample_count, insufficient_data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (model_id, ts, status, reasons_json, metrics_json, samples, insufficient)
            )
        )

        # Bound retention periodically
        self.repository.writer.submit(
            lambda db: db.execute(
                """
                DELETE FROM drift_snapshots WHERE model_id=? AND id NOT IN (
                    SELECT id FROM drift_snapshots WHERE model_id=? ORDER BY id DESC LIMIT ?
                )
                """,
                (model_id, model_id, self.retention_snapshots)
            )
        )

    def summary(self) -> Dict[str, Any]:
        """Provides status for all known models."""
        models = [r["model_id"] for r in self.repository._read("SELECT model_id FROM models")]
        if not models:
            models = ["assurance-audio", "assurance-vision"]
        evaluations = {}
        for m in models:
            evaluations[m] = self.evaluate_model(m)
        return evaluations
