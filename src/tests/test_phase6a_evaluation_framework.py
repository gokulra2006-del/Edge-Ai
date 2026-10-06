"""Tests for the Phase 6A Reproducible Evaluation Framework.

Verifies:
1. Scenario Determinism: Identical seeds produce bit-exact identical scenario hashes.
2. Metrics Correctness: Hand-crafted confusion scenarios yield exact mathematical F1 and rates.
3. Fault Injection Integrity: Camera dropout, audio silence, and noise alter inputs as expected.
4. Honest Data Labeling & Power Tagging: Scenarios tagged with SYNTHETIC/REPLAYED_REAL; power marked NOT_MEASURED.
5. Systems Under Test: Unimodal, static, and temporal-OOD fusion operate across scenarios.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from evaluation.scenarios import (
    FaultInjector,
    ScenarioGenerator,
    Scenario,
)
from evaluation.systems import (
    AudioOnlySystem,
    VisionOnlySystem,
    SensorOnlySystem,
    StaticFusionSystem,
    TemporalOodFusionSystem,
)
from evaluation.metrics import (
    compute_classification_metrics,
    compute_latency_metrics,
    compute_bootstrap_macro_f1_ci,
)
from evaluation.runner import EvaluationHarness


def test_scenario_generator_determinism():
    """Verify identical seeds produce bit-exact identical scenario content and hashes."""
    gen1 = ScenarioGenerator(seed=123)
    gen2 = ScenarioGenerator(seed=123)
    gen3 = ScenarioGenerator(seed=999)

    suite1 = gen1.generate_suite(count_per_class=2, duration_seconds=5.0)
    suite2 = gen2.generate_suite(count_per_class=2, duration_seconds=5.0)
    suite3 = gen3.generate_suite(count_per_class=2, duration_seconds=5.0)

    assert len(suite1) == len(suite2) == len(suite3) == 8

    # Seed 123 must match identically
    for sc1, sc2 in zip(suite1, suite2):
        assert sc1.compute_hash() == sc2.compute_hash()
        assert sc1.scenario_id == sc2.scenario_id
        assert sc1.data_tag == "SYNTHETIC"

    # Seed 999 must diverge
    divergent = any(sc1.compute_hash() != sc3.compute_hash() for sc1, sc3 in zip(suite1, suite3))
    assert divergent, "Different seeds should produce divergent scenario content"


def test_fault_injection_effects():
    """Verify fault injection modifies scenario steps as specified."""
    gen = ScenarioGenerator(seed=42)
    suite = gen.generate_suite(count_per_class=1, duration_seconds=4.0)
    base_sc = suite[0]

    # 1. Camera dropout
    dropped_sc = FaultInjector.inject(base_sc, "camera_dropout")
    assert dropped_sc.fault_type == "camera_dropout"
    assert all(s.vision.fps == 0.0 and len(s.vision.detected_classes) == 0 for s in dropped_sc.steps)

    # 2. Audio silence
    silent_sc = FaultInjector.inject(base_sc, "audio_silence")
    assert silent_sc.fault_type == "audio_silence"
    assert all(s.audio.decibels == 0.0 and s.audio.mel_top_class == "silence" for s in silent_sc.steps)

    # 3. Network outage
    net_sc = FaultInjector.inject(base_sc, "network_outage")
    assert net_sc.fault_type == "network_outage"
    assert all(s.network_online is False for s in net_sc.steps)


def test_hand_crafted_metric_correctness():
    """Verify precision, recall, macro-F1, false-alarm rate on hand-calculated ground truths."""
    # 2 NORMAL, 2 ACCIDENT, 2 FIRE, 2 AMBULANCE
    y_true = ["NORMAL", "NORMAL", "ACCIDENT", "ACCIDENT", "FIRE", "FIRE", "AMBULANCE", "AMBULANCE"]
    # Predict 1 NORMAL as ACCIDENT (false alarm), predict 1 FIRE as NORMAL (miss)
    y_pred = ["NORMAL", "ACCIDENT", "ACCIDENT", "ACCIDENT", "FIRE", "NORMAL", "AMBULANCE", "AMBULANCE"]

    metrics = compute_classification_metrics(y_true, y_pred, bootstrap_rounds=100, seed=42)

    # ACCIDENT: TP=2, FP=1, FN=0 -> Prec=2/3 (~0.6667), Rec=1.0 -> F1 = 2*(2/3)*1 / (5/3) = 0.8
    assert metrics.per_class_f1["ACCIDENT"] == pytest.approx(0.8, 0.01)
    # NORMAL: TP=1, FP=1, FN=1 -> Prec=0.5, Rec=0.5 -> F1=0.5
    assert metrics.per_class_f1["NORMAL"] == pytest.approx(0.5, 0.01)
    # AMBULANCE: TP=2, FP=0, FN=0 -> F1=1.0
    assert metrics.per_class_f1["AMBULANCE"] == 1.0

    # False-Alarm Rate: 1 false alarm out of 2 normals = 50.0%
    assert metrics.false_alarm_rate_pct == 50.0
    # Miss Rate: 1 miss out of 6 emergencies = 16.67%
    assert metrics.miss_rate_pct == pytest.approx(16.67, 0.05)


def test_bootstrap_confidence_interval_bounds():
    """Verify bootstrap CI falls strictly within valid [0.0, 1.0] range and brackets macro-F1."""
    y_true = ["NORMAL", "ACCIDENT", "FIRE", "AMBULANCE"] * 5
    y_pred = ["NORMAL", "ACCIDENT", "FIRE", "AMBULANCE"] * 5  # Perfect score

    ci_low, ci_high = compute_bootstrap_macro_f1_ci(y_true, y_pred, rounds=200, seed=42)
    assert ci_low == pytest.approx(1.0, 0.01)
    assert ci_high == pytest.approx(1.0, 0.01)


def test_systems_under_test_execution(tmp_path):
    """Verify all 5 benchmark systems run end-to-end and emit valid results."""
    gen = ScenarioGenerator(seed=42)
    scenarios = gen.generate_suite(count_per_class=1, duration_seconds=4.0)

    systems = [
        AudioOnlySystem(),
        VisionOnlySystem(),
        SensorOnlySystem(),
        StaticFusionSystem(),
        TemporalOodFusionSystem(),
    ]

    harness = EvaluationHarness(seed=42, results_dir=tmp_path, bootstrap_rounds=50)
    results = harness.run_suite(
        systems=systems,
        scenarios=scenarios,
        faults=["none", "camera_dropout"],
        suite_id="test_run",
    )

    # 5 systems * 2 faults = 10 results
    assert len(results) == 10

    # Verify honest power marking
    for r in results:
        assert r.resources.power_watts is None
        assert r.data_tag == "SYNTHETIC"
        assert len(r.config_hash) == 16

    # Verify export artifacts
    out_dir = harness.export_results(results, "smoke_export")
    assert (out_dir / "metrics.json").exists()
    assert (out_dir / "metrics.csv").exists()
    assert (out_dir / "comparison_table.md").exists()
