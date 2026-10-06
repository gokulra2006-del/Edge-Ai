"""Tests for Phase 6H: Environmental Robustness and Subgroup Fairness Evaluation.
================================================================================
Validates:
1. Environmental conditions metadata in Scenario and Evidence records.
2. Physical perturbations across lighting, weather, camera angle, and acoustics.
3. Low-sample adequacy gating: strictly flags N < min_samples as INSUFFICIENT_DATA without numbers.
4. Per-condition metrics: Macro-F1, FAR, Miss rate, ECE, Brier score, and Bootstrap 95% CIs.
5. Subgroup disparity and fairness gap calculation (best vs worst).
6. Honest data labeling (SYNTHETIC, REPLAYED_REAL, REAL_HARDWARE).
7. Artifact exports (JSON, CSV, HTML) usability and consistency.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import pytest

from evaluation.metrics import compute_bootstrap_far_ci, compute_bootstrap_miss_ci
from evaluation.robustness import (
    DIMENSIONS,
    ConditionEvaluationResult,
    DimensionDisparitySummary,
    REAL_DATA_CONDITIONS,
    RobustnessEvaluator,
    RobustnessSuiteResult,
)
from evaluation.scenarios import (
    EnvironmentalConditions,
    Scenario,
    ScenarioGenerator,
    ScenarioStep,
    SensorReading,
    AudioReading,
    VisionReading,
)
from evaluation.systems import TemporalOodFusionSystem, StaticFusionSystem
from src.modules.database.governed_store import GovernanceConfig, IncidentRepository


@pytest.fixture
def governed_repo(tmp_path):
    repo = IncidentRepository(tmp_path / "phase6h_test.db", GovernanceConfig())
    yield repo
    repo.close()


def test_environmental_conditions_metadata_in_scenario():
    """Verify EnvironmentalConditions dataclass, hash determinism, and serialization."""
    cond_default = EnvironmentalConditions()
    assert cond_default.time_of_day == "day"
    assert cond_default.weather == "clear"
    assert cond_default.camera_angle == "overhead"

    cond_custom = EnvironmentalConditions(
        time_of_day="night",
        weather="fog",
        camera_angle="oblique",
        traffic_density="high",
        microphone_placement="enclosed",
        road_surface="wet_concrete",
        acoustic_zone="noisy_intersection",
        hardware_node="jetson_node2",
    )

    d = cond_custom.to_dict()
    assert d["time_of_day"] == "night"
    assert d["weather"] == "fog"

    restored = EnvironmentalConditions.from_dict(d)
    assert restored == cond_custom

    # Scenario hashing with conditions
    gen = ScenarioGenerator(seed=101)
    suite = gen.generate_suite(count_per_class=1, duration_seconds=4.0)
    sc = suite[0]
    sc.conditions = cond_custom

    h1 = sc.compute_hash()
    h2 = sc.compute_hash()
    assert h1 == h2, "Hash must be strictly deterministic"

    # Divergence when condition altered
    sc_alt = Scenario.from_dict(sc.to_dict())
    sc_alt.conditions.weather = "rain"
    assert sc.compute_hash() != sc_alt.compute_hash()


def test_evidence_condition_metadata_persistence(governed_repo, tmp_path):
    """Verify evidence table stores condition metadata alongside source and sha256."""
    inc_id, _ = governed_repo.create_incident("ACCIDENT", "ZONE_A")
    governed_repo.writer.drain()

    dummy_file = tmp_path / "evidence_sample.jpg"
    dummy_file.write_bytes(b"dummy_image_bytes_12345")

    conditions = {
        "time_of_day": "night",
        "weather": "rain",
        "camera_angle": "street_level",
        "hardware_node": "rpi4_node1",
    }

    governed_repo.attach_evidence(
        incident_id=inc_id,
        kind="KEYFRAME",
        source=dummy_file,
        condition_metadata=conditions,
    )
    governed_repo.writer.drain()

    rows = governed_repo._read("SELECT * FROM evidence WHERE incident_id=?", (inc_id,))
    assert len(rows) == 1
    ev_row = dict(rows[0])
    assert ev_row["kind"] == "KEYFRAME"
    assert ev_row["sha256"] is not None

    meta = json.loads(ev_row["condition_metadata_json"])
    assert meta["time_of_day"] == "night"
    assert meta["weather"] == "rain"
    assert meta["hardware_node"] == "rpi4_node1"


def test_physical_perturbations_in_generator():
    """Verify that adverse conditions realistically perturb vision and acoustic sensor outputs."""
    gen = ScenarioGenerator(seed=42, step_duration=1.0)

    # 1. Nominal scenario (day, clear)
    cond_nominal = EnvironmentalConditions(time_of_day="day", weather="clear")
    sc_nominal = gen._generate_single_scenario(
        scenario_id="S1", name="Nominal", zone="Z1", event_class="FIRE",
        duration_seconds=5.0, rng=gen.__class__(seed=42)._get_rng_if_needed(42) if hasattr(gen, "_get_rng_if_needed") else __import__("random").Random(42),
        data_tag="SYNTHETIC", conditions=cond_nominal,
    )

    # 2. Night + Fog scenario
    cond_adverse = EnvironmentalConditions(time_of_day="night", weather="fog")
    sc_adverse = gen._generate_single_scenario(
        scenario_id="S2", name="Adverse", zone="Z1", event_class="FIRE",
        duration_seconds=5.0, rng=__import__("random").Random(42),
        data_tag="SYNTHETIC", conditions=cond_adverse,
    )

    # Vision confidence in adverse conditions must be attenuated
    nom_conf = sc_nominal.steps[3].vision.confidences.get("fire", 1.0)
    adv_conf = sc_adverse.steps[3].vision.confidences.get("fire", 1.0)
    assert adv_conf < nom_conf, f"Adverse vision confidence ({adv_conf}) should be lower than nominal ({nom_conf})"


def test_insufficient_data_gating():
    """Verify subgroups with sample count < min_samples are flagged INSUFFICIENT_DATA with no numbers."""
    gen = ScenarioGenerator(seed=77)
    # Generate small suite (only 1 scenario per class for 2 conditions)
    cond_rare = EnvironmentalConditions(weather="fog")
    sc_rare = gen._generate_single_scenario(
        scenario_id="RARE-01", name="Rare Fog", zone="Z1", event_class="NORMAL",
        duration_seconds=2.0, rng=__import__("random").Random(77),
        data_tag="SYNTHETIC", conditions=cond_rare,
    )  # Has only 2 steps (duration 2.0 / step 1.0 = 2)

    system = TemporalOodFusionSystem()
    # Require min_samples = 10
    evaluator = RobustnessEvaluator(min_samples=10, seed=77)
    result = evaluator.evaluate(system, [sc_rare])

    # Find the weather=fog result
    fog_res = next(r for r in result.condition_results if r.dimension == "weather" and r.condition_value == "fog")
    assert fog_res.status == "INSUFFICIENT_DATA"
    assert fog_res.sample_count < 10
    assert fog_res.macro_f1 is None
    assert fog_res.false_alarm_rate_pct is None
    assert fog_res.miss_rate_pct is None
    assert fog_res.ece is None
    assert "INSUFFICIENT_DATA" in fog_res.notes


def test_robustness_metrics_and_calibration():
    """Verify Macro-F1, FAR, Miss rate, calibration ECE, and bootstrap CIs on a multi-condition suite."""
    gen = ScenarioGenerator(seed=42)
    # Generate 2 scenarios per condition (enough samples > 10 per condition)
    suite = gen.generate_robustness_suite(count_per_condition=4, duration_seconds=6.0)

    system = TemporalOodFusionSystem()
    evaluator = RobustnessEvaluator(min_samples=8, bootstrap_rounds=100, seed=42)
    result = evaluator.evaluate(system, suite)

    assert result.total_evaluated_scenarios > 0
    assert result.total_evaluated_steps > 0
    assert result.nominal_baseline_metrics["macro_f1"] > 0.0

    valid_results = [r for r in result.condition_results if r.status == "VALID"]
    assert len(valid_results) > 0

    for r in valid_results:
        assert 0.0 <= (r.macro_f1 or 0.0) <= 1.0
        assert r.ci_macro_f1 is not None
        assert r.ci_macro_f1[0] <= r.ci_macro_f1[1]
        assert r.false_alarm_rate_pct is not None
        assert r.miss_rate_pct is not None
        assert r.ece is not None
        assert 0.0 <= r.ece <= 1.0
        assert r.brier_score is not None
        assert 0.0 <= r.brier_score <= 1.0


def test_disparity_and_fairness_gap_analysis():
    """Verify disparity gap calculation across condition dimensions."""
    gen = ScenarioGenerator(seed=42)
    suite = gen.generate_robustness_suite(count_per_condition=4, duration_seconds=6.0)

    system = TemporalOodFusionSystem()
    evaluator = RobustnessEvaluator(min_samples=5, bootstrap_rounds=50, seed=42)
    result = evaluator.evaluate(system, suite)

    # Every dimension in DIMENSIONS must have a disparity summary
    for dim in DIMENSIONS:
        assert dim in result.dimension_disparities
        disp = result.dimension_disparities[dim]
        assert disp.dimension == dim
        if disp.best_macro_f1 is not None and disp.worst_macro_f1 is not None:
            assert disp.best_macro_f1 >= disp.worst_macro_f1
            assert disp.disparity_gap_f1 is not None
            assert disp.disparity_gap_f1 >= 0.0
            assert disp.best_condition is not None
            assert disp.worst_condition is not None

    # Hypothesis confirmation: overall performance divergence detected across conditions
    assert result.hypothesis_confirmed is True


def test_data_provenance_and_real_hardware_tagging():
    """Verify every result carries honest tags and real-data disclosure matches deployed specs."""
    gen = ScenarioGenerator(seed=42)
    suite = gen.generate_robustness_suite(count_per_condition=4, duration_seconds=4.0)

    evaluator = RobustnessEvaluator(min_samples=5, seed=42)
    result = evaluator.evaluate(TemporalOodFusionSystem(), suite)

    allowed_tags = {"SYNTHETIC", "REPLAYED_REAL", "REAL_HARDWARE"}
    for r in result.condition_results:
        assert r.data_tag in allowed_tags

    # Real data conditions must be correctly flagged
    day_res = next(r for r in result.condition_results if r.dimension == "time_of_day" and r.condition_value == "day")
    assert day_res.has_real_data is True

    # Disclosure text must be present
    assert "Raspberry Pi 4 (rpi4_node1)" in result.real_data_disclosure["disclosure_text"]


def test_artifact_exports_json_csv_html(tmp_path):
    """Verify export_json, export_csv, and export_html generate valid, readable reports."""
    gen = ScenarioGenerator(seed=42)
    suite = gen.generate_robustness_suite(count_per_condition=4, duration_seconds=4.0)

    evaluator = RobustnessEvaluator(min_samples=5, seed=42)
    result = evaluator.evaluate(TemporalOodFusionSystem(), suite)

    json_path = tmp_path / "eval.json"
    csv_path = tmp_path / "eval.csv"
    html_path = tmp_path / "eval.html"

    evaluator.export_json(result, json_path)
    evaluator.export_csv(result, csv_path)
    evaluator.export_html(result, html_path)

    # 1. JSON
    assert json_path.is_file()
    with open(json_path, "r", encoding="utf-8") as f:
        loaded_json = json.load(f)
    assert loaded_json["git_hash"] is not None
    assert len(loaded_json["condition_results"]) > 0

    # 2. CSV
    assert csv_path.is_file()
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) > 0
    assert "macro_f1" in rows[0]
    assert "data_tag" in rows[0]
    assert "has_real_data" in rows[0]

    # 3. HTML
    assert html_path.is_file()
    html_text = html_path.read_text(encoding="utf-8")
    assert "Sentinel-AI Environmental Robustness" in html_text
    assert "Subgroup Disparities & Fairness Gaps" in html_text
    assert "Data Origin & Provenance Disclosure" in html_text
