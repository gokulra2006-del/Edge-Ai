"""Evaluation metrics computation, bootstrap confidence intervals, and resource accounting."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from evaluation.scenarios import EventClass


@dataclass
class ClassificationMetrics:
    macro_f1: float
    per_class_f1: Dict[str, float]
    per_class_precision: Dict[str, float]
    per_class_recall: Dict[str, float]
    false_alarm_rate_pct: float
    miss_rate_pct: float
    accuracy_pct: float
    total_samples: int
    bootstrap_ci_macro_f1: Tuple[float, float] = (0.0, 0.0)


@dataclass
class LatencyMetrics:
    mean_detection_latency_seconds: Optional[float]
    median_detection_latency_seconds: Optional[float]
    p95_detection_latency_seconds: Optional[float]
    mean_tta_seconds: Optional[float]
    mean_ttr_seconds: Optional[float]
    detected_count: int
    total_events: int


@dataclass
class ResourceMetrics:
    cpu_usage_pct: Optional[float] = None
    memory_peak_mb: Optional[float] = None
    bandwidth_bytes_sec: Optional[float] = None
    power_watts: Optional[float] = None  # None -> NOT_MEASURED (never silently estimated)
    measurement_status: str = "MEASURED"


@dataclass
class SystemEvaluationResult:
    system_name: str
    scenario_set: str
    fault_type: str
    data_tag: str
    classification: ClassificationMetrics
    latency: LatencyMetrics
    resources: ResourceMetrics
    config_hash: str
    metadata: Dict[str, Any] = field(default_factory=dict)


def compute_classification_metrics(
    y_true: List[EventClass],
    y_pred: List[EventClass],
    bootstrap_rounds: int = 1000,
    seed: int = 42,
) -> ClassificationMetrics:
    classes = ["NORMAL", "ACCIDENT", "FIRE", "AMBULANCE"]
    n = len(y_true)
    if n == 0:
        return ClassificationMetrics(
            macro_f1=0.0,
            per_class_f1={c: 0.0 for c in classes},
            per_class_precision={c: 0.0 for c in classes},
            per_class_recall={c: 0.0 for c in classes},
            false_alarm_rate_pct=0.0,
            miss_rate_pct=0.0,
            accuracy_pct=0.0,
            total_samples=0,
        )

    f1s: Dict[str, float] = {}
    precs: Dict[str, float] = {}
    recs: Dict[str, float] = {}

    for c in classes:
        tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == c and yp == c)
        fp = sum(1 for yt, yp in zip(y_true, y_pred) if yt != c and yp == c)
        fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == c and yp != c)

        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0

        f1s[c] = round(f1, 4)
        precs[c] = round(prec, 4)
        recs[c] = round(rec, 4)

    macro_f1 = round(sum(f1s.values()) / len(classes), 4)
    accuracy = round((sum(1 for yt, yp in zip(y_true, y_pred) if yt == yp) / n) * 100.0, 2)

    # False alarm rate: when true is NORMAL but pred is an emergency alert
    normals = sum(1 for yt in y_true if yt == "NORMAL")
    false_alarms = sum(1 for yt, yp in zip(y_true, y_pred) if yt == "NORMAL" and yp != "NORMAL")
    far_pct = round((false_alarms / normals * 100.0) if normals > 0 else 0.0, 2)

    # Miss rate: when true is emergency but pred is NORMAL
    emergencies = sum(1 for yt in y_true if yt != "NORMAL")
    misses = sum(1 for yt, yp in zip(y_true, y_pred) if yt != "NORMAL" and yp == "NORMAL")
    miss_pct = round((misses / emergencies * 100.0) if emergencies > 0 else 0.0, 2)

    # Bootstrap 95% Confidence Interval for Macro-F1
    ci = compute_bootstrap_macro_f1_ci(y_true, y_pred, rounds=bootstrap_rounds, seed=seed)

    return ClassificationMetrics(
        macro_f1=macro_f1,
        per_class_f1=f1s,
        per_class_precision=precs,
        per_class_recall=recs,
        false_alarm_rate_pct=far_pct,
        miss_rate_pct=miss_pct,
        accuracy_pct=accuracy,
        total_samples=n,
        bootstrap_ci_macro_f1=ci,
    )


def compute_bootstrap_macro_f1_ci(
    y_true: List[EventClass],
    y_pred: List[EventClass],
    rounds: int = 1000,
    seed: int = 42,
) -> Tuple[float, float]:
    n = len(y_true)
    if n < 5:
        return (0.0, 1.0)

    rng = random.Random(seed)
    scores: List[float] = []
    classes = ["NORMAL", "ACCIDENT", "FIRE", "AMBULANCE"]

    indices = list(range(n))
    for _ in range(rounds):
        sample_idx = [rng.choice(indices) for _ in range(n)]
        sampled_true = [y_true[i] for i in sample_idx]
        sampled_pred = [y_pred[i] for i in sample_idx]

        f1_vals: List[float] = []
        for c in classes:
            tp = sum(1 for yt, yp in zip(sampled_true, sampled_pred) if yt == c and yp == c)
            fp = sum(1 for yt, yp in zip(sampled_true, sampled_pred) if yt != c and yp == c)
            fn = sum(1 for yt, yp in zip(sampled_true, sampled_pred) if yt == c and yp != c)
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
            f1_vals.append(f1)

        scores.append(sum(f1_vals) / len(classes))

    scores.sort()
    low_idx = int(rounds * 0.025)
    high_idx = int(rounds * 0.975)
    return (round(scores[low_idx], 4), round(scores[high_idx], 4))


def compute_bootstrap_far_ci(
    y_true: List[EventClass],
    y_pred: List[EventClass],
    rounds: int = 1000,
    seed: int = 42,
) -> Tuple[float, float]:
    normals_idx = [i for i, yt in enumerate(y_true) if yt == "NORMAL"]
    if len(normals_idx) < 5:
        return (0.0, 100.0)

    rng = random.Random(seed)
    rates: List[float] = []
    n_norm = len(normals_idx)

    for _ in range(rounds):
        sample_idx = [rng.choice(normals_idx) for _ in range(n_norm)]
        fa = sum(1 for i in sample_idx if y_pred[i] != "NORMAL")
        rates.append((fa / n_norm) * 100.0)

    rates.sort()
    low_idx = int(rounds * 0.025)
    high_idx = int(rounds * 0.975)
    return (round(rates[low_idx], 2), round(rates[high_idx], 2))


def compute_bootstrap_miss_ci(
    y_true: List[EventClass],
    y_pred: List[EventClass],
    rounds: int = 1000,
    seed: int = 42,
) -> Tuple[float, float]:
    emergencies_idx = [i for i, yt in enumerate(y_true) if yt != "NORMAL"]
    if len(emergencies_idx) < 5:
        return (0.0, 100.0)

    rng = random.Random(seed)
    rates: List[float] = []
    n_em = len(emergencies_idx)

    for _ in range(rounds):
        sample_idx = [rng.choice(emergencies_idx) for _ in range(n_em)]
        miss = sum(1 for i in sample_idx if y_pred[i] == "NORMAL")
        rates.append((miss / n_em) * 100.0)

    rates.sort()
    low_idx = int(rounds * 0.025)
    high_idx = int(rounds * 0.975)
    return (round(rates[low_idx], 2), round(rates[high_idx], 2))


def compute_latency_metrics(
    latencies: List[float],
    total_events: int,
    simulated_tta: List[float],
    simulated_ttr: List[float],
) -> LatencyMetrics:
    if not latencies:
        return LatencyMetrics(
            mean_detection_latency_seconds=None,
            median_detection_latency_seconds=None,
            p95_detection_latency_seconds=None,
            mean_tta_seconds=None,
            mean_ttr_seconds=None,
            detected_count=0,
            total_events=total_events,
        )

    sorted_lats = sorted(latencies)
    n = len(sorted_lats)
    mean_lat = round(sum(sorted_lats) / n, 3)
    med_lat = round(sorted_lats[n // 2], 3)
    p95_idx = min(n - 1, int(n * 0.95))
    p95_lat = round(sorted_lats[p95_idx], 3)

    mean_tta = round(sum(simulated_tta) / len(simulated_tta), 2) if simulated_tta else None
    mean_ttr = round(sum(simulated_ttr) / len(simulated_ttr), 2) if simulated_ttr else None

    return LatencyMetrics(
        mean_detection_latency_seconds=mean_lat,
        median_detection_latency_seconds=med_lat,
        p95_detection_latency_seconds=p95_lat,
        mean_tta_seconds=mean_tta,
        mean_ttr_seconds=mean_ttr,
        detected_count=n,
        total_events=total_events,
    )
