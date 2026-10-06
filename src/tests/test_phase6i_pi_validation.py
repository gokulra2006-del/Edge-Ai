"""Tests for Phase 6I: Real deployment validation tooling.

Validates:
1. Hardware metadata extraction and signature generation/verification in common.py.
2. Throttled bitmask detection and parsing.
3. Network recovery offline buffering & flush tracking.
4. Power recovery pre-power cut preparation & post-power cut integrity checks.
5. Strict anti-fabrication import validation (rejection of tampered, synthetic, or unsigned results).
6. Paper report generation showing NOT_MEASURED for missing values in Markdown and LaTeX.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
import pytest

from scripts.pi.common import (
    create_benchmark_header,
    verify_benchmark_header,
    compute_benchmark_signature,
    get_hardware_model,
    get_os_info,
    get_git_hash,
    THROTTLE_FLAGS,
)
from scripts.pi.test_network_recovery import run_network_recovery_benchmark
from scripts.pi.test_power_recovery import prepare_power_cut, verify_power_recovery
from scripts.pi.import_results import import_validation_results
from scripts.pi.generate_paper_report import format_val, generate_paper_table, export_paper_tables


def test_hardware_metadata_and_signature():
    """Verify hardware metadata collection and cryptographic HMAC signatures."""
    hw_model = get_hardware_model()
    os_info = get_os_info()
    git_hash = get_git_hash()

    assert isinstance(hw_model, str) and len(hw_model) > 0
    assert isinstance(os_info, str) and len(os_info) > 0
    assert isinstance(git_hash, str) and len(git_hash) > 0

    header = create_benchmark_header("cpu_memory", duration_seconds=10.0, repeatable=True)
    assert header["benchmark"] == "cpu_memory"
    assert header["data_tag"] == "REAL_HARDWARE"
    assert "signature" in header

    valid, reason = verify_benchmark_header(header)
    assert valid is True
    assert "Valid" in reason

    # Tamper test: modify one field
    header_tampered = dict(header)
    header_tampered["hardware_model"] = "Faked_Pi_5"
    valid_tampered, reason_tampered = verify_benchmark_header(header_tampered)
    assert valid_tampered is False
    assert "signature mismatch" in reason_tampered.lower()


def test_throttle_flags():
    """Verify throttle flag bit definitions."""
    assert 0x1 in THROTTLE_FLAGS
    assert 0x2 in THROTTLE_FLAGS
    assert 0x4 in THROTTLE_FLAGS
    assert 0x8 in THROTTLE_FLAGS
    assert 0x10000 in THROTTLE_FLAGS


def test_network_recovery_offline_buffering(tmp_path: Path):
    """Verify network recovery test offline queue creation and flush throughput."""
    db_path = tmp_path / "test_outbox.db"
    result = run_network_recovery_benchmark(test_duration_seconds=5.0, generated_events=5, db_path=db_path)

    assert "header" in result
    assert result["header"]["benchmark"] == "network_outage_recovery"
    assert result["header"]["data_tag"] == "REAL_HARDWARE"
    assert verify_benchmark_header(result["header"])[0] is True

    metrics = result["metrics"]
    assert metrics["events_enqueued_offline"] == 5
    assert metrics["events_successfully_flushed"] == 5
    assert metrics["unflushed_backlog_remaining"] == 0
    assert metrics["zero_dropped_events"] is True


def test_power_recovery_prepare_and_verify(tmp_path: Path):
    """Verify power recovery preparation and post-restart integrity checks."""
    db_path = tmp_path / "test_edge.db"
    marker_path = tmp_path / "marker.json"

    # 1. Prepare phase
    # Temporarily redirect marker path
    import scripts.pi.test_power_recovery as pwr_mod
    original_marker = pwr_mod.MARKER_PATH
    try:
        pwr_mod.MARKER_PATH = marker_path
        marker_data = prepare_power_cut(db_path, count=4)
        assert marker_data["expected_actions_count"] == 4
        assert marker_path.exists()

        # 2. Verify phase
        verify_result = verify_power_recovery(db_path=db_path, marker_path=marker_path)
        assert verify_result["metrics"]["sqlite_integrity_check"] == "ok"
        assert verify_result["metrics"]["lost_audit_records_count"] == 0
        assert verify_result["metrics"]["audit_retention_rate_pct"] == 100.0
        assert verify_result["metrics"]["status"] == "PASS"
        assert verify_benchmark_header(verify_result["header"])[0] is True
    finally:
        pwr_mod.MARKER_PATH = original_marker


def test_import_results_anti_fabrication(tmp_path: Path):
    """Ensure import_results enforces cryptographic signature and REAL_HARDWARE tag."""
    dest_path = tmp_path / "hardware_validation.json"

    # 1. Reject fake / synthetic tag
    fake_payload = {
        "header": {
            "benchmark": "cpu_memory",
            "data_tag": "SYNTHETIC",
            "hardware_model": "Generic",
            "timestamp_utc": "2026-10-07T00:00:00Z",
            "git_hash": "12345678",
            "signature": "fake-sig",
        }
    }
    fake_file = tmp_path / "fake.json"
    fake_file.write_text(json.dumps(fake_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="must be 'REAL_HARDWARE'"):
        import_validation_results(fake_file, target_results_file=dest_path)

    # 2. Reject tampered signature
    valid_header = create_benchmark_header("cpu_memory", duration_seconds=5.0)
    valid_header["signature"] = "invalid_hash_signature"
    tampered_file = tmp_path / "tampered.json"
    tampered_file.write_text(json.dumps({"header": valid_header}), encoding="utf-8")

    with pytest.raises(ValueError, match="signature mismatch"):
        import_validation_results(tampered_file, target_results_file=dest_path)

    # 3. Accept valid signed bundle
    bundle_header = create_benchmark_header("consolidated_pi_validation_bundle", duration_seconds=10.0)
    cpu_header = create_benchmark_header("cpu_memory", duration_seconds=5.0)
    bundle_data = {
        "bundle_header": bundle_header,
        "benchmarks": {
            "cpu_memory": {
                "header": cpu_header,
                "summary": {"cpu_percent_avg": 42.5, "process_rss_mb_avg": 68.2},
            }
        }
    }
    bundle_file = tmp_path / "valid_bundle.json"
    bundle_file.write_text(json.dumps(bundle_data), encoding="utf-8")

    imported = import_validation_results(bundle_file, target_results_file=dest_path)
    assert imported["status"] == "AUTHENTICATED"
    assert imported["data_tag"] == "REAL_HARDWARE"
    assert "cpu_memory" in imported["benchmarks"]
    assert dest_path.exists()


def test_generate_paper_report_not_measured(tmp_path: Path):
    """Verify that unmeasured metrics explicitly render as NOT_MEASURED without fabrication."""
    assert format_val(None, "FPS") == "NOT_MEASURED"
    assert format_val("UNAVAILABLE", "FPS") == "NOT_MEASURED"
    assert format_val(30.0, "FPS") == "30.0 FPS"

    # Minimal validation data with only CPU measured
    bundle_header = create_benchmark_header("consolidated_pi_validation_bundle", duration_seconds=10.0)
    cpu_header = create_benchmark_header("cpu_memory", duration_seconds=5.0)
    validation_data = {
        "status": "AUTHENTICATED",
        "data_tag": "REAL_HARDWARE",
        "bundle_header": bundle_header,
        "benchmarks": {
            "cpu_memory": {
                "header": cpu_header,
                "summary": {"cpu_percent_avg": 38.4, "process_rss_mb_avg": 75.1},
            }
        }
    }
    table_data = generate_paper_table(validation_data)
    md_table = table_data["markdown_table"]
    latex_table = table_data["latex_table"]

    assert "38.4 %" in md_table
    assert "NOT_MEASURED" in md_table
    assert "Camera Throughput" in md_table
    assert "NOT\\_MEASURED" in latex_table
    assert "\\begin{table" in latex_table

    input_file = tmp_path / "hardware_validation.json"
    input_file.write_text(json.dumps(validation_data), encoding="utf-8")
    md_out = tmp_path / "table.md"
    tex_out = tmp_path / "table.tex"

    export_paper_tables(input_file, md_out, tex_out)
    assert md_out.exists()
    assert tex_out.exists()
    assert "NOT_MEASURED" in md_out.read_text(encoding="utf-8")


def test_individual_benchmarks_execution(tmp_path: Path):
    """Verify execution of CPU, Thermal, Storage, and Bus benchmarks with authenticated headers."""
    import scripts.pi.benchmark_cpu_memory as bench_cpu
    import scripts.pi.benchmark_thermal as bench_thermal
    import scripts.pi.benchmark_storage_latency as bench_storage
    import scripts.pi.benchmark_sensor_contention as bench_bus

    # 1. CPU
    cpu_res = bench_cpu.run_benchmark(duration_seconds=1, sample_interval=0.2)
    assert cpu_res["header"]["data_tag"] == "REAL_HARDWARE"
    assert verify_benchmark_header(cpu_res["header"])[0] is True
    assert "summary" in cpu_res

    # 2. Thermal
    thermal_res = bench_thermal.run_benchmark()
    assert thermal_res["header"]["data_tag"] == "REAL_HARDWARE"
    assert verify_benchmark_header(thermal_res["header"])[0] is True
    assert "throttling" in thermal_res

    # 3. Storage
    storage_res = bench_storage.run_benchmark(target_dir=str(tmp_path), random_4k_ops=5, seq_64k_ops=2)
    assert storage_res["header"]["data_tag"] == "REAL_HARDWARE"
    assert verify_benchmark_header(storage_res["header"])[0] is True
    assert "summary" in storage_res

    # 4. Bus contention
    bus_res = bench_bus.run_benchmark(concurrency=2, operations_per_thread=5)
    assert bus_res["header"]["data_tag"] == "REAL_HARDWARE"
    assert verify_benchmark_header(bus_res["header"])[0] is True
    assert "summary" in bus_res


def test_run_all_validation_bundle(tmp_path: Path):
    """Verify master runner executes and produces a valid bundle JSON."""
    from scripts.pi.run_all_validation import run_all_benchmarks

    bundle_path = tmp_path / "bundle.json"
    bundle = run_all_benchmarks(duration_scale=0.1, output_bundle_path=bundle_path)

    assert "bundle_header" in bundle
    assert bundle["bundle_header"]["data_tag"] == "REAL_HARDWARE"
    assert verify_benchmark_header(bundle["bundle_header"])[0] is True
    assert "benchmarks" in bundle
    assert bundle_path.exists()

