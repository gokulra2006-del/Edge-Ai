"""Tests for Phase 6R Headline Comparison Table and Multi-System Evaluation."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from scripts.eval.evaluate_phase6r_headline import (
    HEADLINE_SYSTEMS,
    run_headline_evaluation,
)


def test_headline_systems_configuration():
    """Verify all 6 required headline benchmark systems are configured."""
    assert len(HEADLINE_SYSTEMS) == 6
    keys = [s["key"] for s in HEADLINE_SYSTEMS]
    assert "audio_only" in keys
    assert "vision_only" in keys
    assert "static_fusion" in keys
    assert "adaptive_fusion" in keys
    assert "adaptive_sensor_failure" in keys
    assert "adaptive_network_failure" in keys


def test_headline_evaluation_execution(tmp_path: Path):
    """Run headline evaluation on a small scenario batch and verify generated artifacts."""
    output_dir = tmp_path / "results_test"
    benchmarks, out_dir = run_headline_evaluation(
        num_scenarios=4,
        seed=42,
        bootstrap_rounds=100,
        output_dir=output_dir,
    )

    assert len(benchmarks) == 6

    # Verify all expected artifacts exist offline
    csv_file = output_dir / "headline_comparison_table.csv"
    md_file = output_dir / "headline_comparison_table.md"
    json_file = output_dir / "headline_comparison_metrics.json"
    plot_f1 = output_dir / "plot_headline_macro_f1.png"
    plot_trade = output_dir / "plot_headline_tradeoffs.png"

    assert csv_file.exists(), "CSV table missing"
    assert md_file.exists(), "Markdown table missing"
    assert json_file.exists(), "JSON metrics missing"
    assert plot_f1.exists(), "Macro-F1 plot missing"
    assert plot_trade.exists(), "Tradeoff plot missing"

    # Verify JSON content and statistical bootstrap validity
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "benchmarks" in data
    benchmarks_data = data["benchmarks"]
    assert len(benchmarks_data) == 6

    for record in benchmarks_data:
        assert "system_key" in record
        assert "macro_f1" in record
        assert "ci_macro_f1" in record
        ci_low, ci_high = record["ci_macro_f1"]
        assert ci_low <= record["macro_f1"] + 1e-4
        assert record["macro_f1"] <= ci_high + 1e-4
        assert record["hardware_status"] in ("SIMULATED_HOST", "REAL_HARDWARE", "NOT_MEASURED")
        assert record["data_tag"] == "SYNTHETIC"

    # Verify Network failure invariance: adaptive fusion vs adaptive fusion under network failure
    nom = next(m for m in benchmarks_data if m["system_key"] == "adaptive_fusion")
    net_fail = next(m for m in benchmarks_data if m["system_key"] == "adaptive_network_failure")
    assert abs(nom["macro_f1"] - net_fail["macro_f1"]) < 1e-5, (
        f"Network failure must not alter offline edge F1: {nom['macro_f1']} vs {net_fail['macro_f1']}"
    )
