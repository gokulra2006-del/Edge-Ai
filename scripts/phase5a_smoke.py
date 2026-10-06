#!/usr/bin/env python3
"""Phase 5A Analytics Smoke Test and Query Latency Benchmark.

Validates read-only analytics query engine, incremental rollups,
consistent envelope shapes, and benchmarks query latency.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.governance_config import GovernanceConfig
from src.modules.database.governed_store import IncidentRepository, MigrationRunner
from src.modules.analytics.analytics_engine import AnalyticsEngine
from src.modules.analytics.filters import AnalyticsFilter
from src.modules.analytics.rollup_engine import RollupEngine


def seed_synthetic_dataset(db_file: Path) -> None:
    """Seed 30 days of multi-zone, multi-severity synthetic data."""
    base_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    zones = ["ZONE_NORTH", "ZONE_SOUTH", "ZONE_EAST", "ZONE_WEST"]
    severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    event_types = ["FIRE", "COLLISION", "HAZARD", "NEAR_MISS"]

    with sqlite3.connect(db_file) as con:
        # 1. Incidents
        for i in range(120):
            day_offset = i % 30
            dt = base_date + timedelta(days=day_offset, hours=i % 24, minutes=i % 60)
            iso = dt.isoformat()
            zone = zones[i % len(zones)]
            sev = severities[i % len(severities)]
            ev_type = event_types[i % len(event_types)]
            status = "FALSE_ALARM" if i % 6 == 0 else ("RESOLVED" if i % 2 == 0 else "OPEN")
            ack = 12.0 + (i % 30)
            res = 60.0 + (i % 180) if status in ("RESOLVED", "FALSE_ALARM") else None

            con.execute(
                """
                INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status,
                                      created_at, updated_at, severity, acknowledged_seconds,
                                      resolution_seconds, assurance_level, is_demo)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'FULL', 0)
                """,
                (f"INC-{i:04d}", f"uuid-{i:04d}", ev_type, zone, status, iso, iso, sev, ack, res)
            )

        # 2. Predictions
        for i in range(80):
            dt = base_date + timedelta(days=i % 30, hours=10)
            iso = dt.isoformat()
            conf = 0.65 + (i % 35) * 0.01
            is_ood = (i % 5 == 0)
            payload = json.dumps({"ood_status": "OOD" if is_ood else "IN_DISTRIBUTION"})
            con.execute(
                """
                INSERT INTO predictions(id, incident_id, timestamp, label, confidence, model_id, payload_json)
                VALUES(?, ?, ?, 'HAZARD', ?, 'edge-vision-v1', ?)
                """,
                (i + 1, f"INC-{i:04d}", iso, conf, payload)
            )

        # 3. Prediction Feedback
        for i in range(50):
            dt = base_date + timedelta(days=i % 30, hours=11)
            iso = dt.isoformat()
            label = "CORRECT" if i % 4 != 0 else "INCORRECT"
            corrected = None if label == "CORRECT" else "NORMAL"
            con.execute(
                """
                INSERT INTO prediction_feedback(prediction_id, label, corrected_class, operator_id, operator_role, timestamp)
                VALUES(?, ?, ?, 'op_smoke', 'OPERATOR', ?)
                """,
                (i + 1, label, corrected, iso)
            )

        # 4. Drift Snapshots
        for i in range(15):
            dt = base_date + timedelta(days=i * 2, hours=14)
            iso = dt.isoformat()
            st = "STABLE" if i < 10 else ("DRIFT_WARNING" if i < 13 else "DRIFT_DETECTED")
            psi = 0.03 + (i * 0.02)
            con.execute(
                """
                INSERT INTO drift_snapshots(model_id, timestamp, status, reasons_json, metrics_json, sample_count, insufficient_data)
                VALUES('edge-vision-v1', ?, ?, '[]', ?, 200, 0)
                """,
                (iso, st, json.dumps({"psi": round(psi, 3)}))
            )

        # 5. Device Health Events
        con.execute(
            """
            INSERT INTO device_health_events(timestamp, component, previous_status, current_status, reason_code, message, details_json)
            VALUES(?, 'camera', 'OK', 'OK', 'nominal', 'healthy', '{}')
            """,
            (base_date.isoformat(),)
        )
        con.execute(
            """
            INSERT INTO device_health_events(timestamp, component, previous_status, current_status, reason_code, message, details_json)
            VALUES(?, 'audio', 'OK', 'OK', 'nominal', 'healthy', '{}')
            """,
            (base_date.isoformat(),)
        )
        con.execute(
            """
            INSERT INTO device_health_events(timestamp, component, previous_status, current_status, reason_code, message, details_json)
            VALUES(?, 'audio', 'OK', 'DOWN', 'fault', 'device disconnected', '{}')
            """,
            ((base_date + timedelta(days=12)).isoformat(),)
        )

        # 6. Outbox Events
        for i in range(30):
            dt = base_date + timedelta(days=i, hours=16)
            iso = dt.isoformat()
            st = "SYNCED" if i < 20 else ("PENDING" if i < 28 else "DEAD_LETTER")
            con.execute(
                """
                INSERT INTO sync_outbox(idempotency_key, target, payload_type, attempts, next_attempt_at, status, priority, last_error, created_at, updated_at, payload_json)
                VALUES(?, 'cloud', 'telemetry', 1, ?, ?, 'LOW', NULL, ?, ?, '{}')
                """,
                (f"outbox-{i}", iso, st, iso, iso)
            )


def benchmark_helper(engine: AnalyticsEngine, filt: AnalyticsFilter, iterations: int = 50) -> dict[str, dict[str, float]]:
    """Benchmark query latencies across multiple query types."""
    results: dict[str, list[float]] = {
        "rollup_timeseries": [],
        "raw_timeseries": [],
        "incident_summary": [],
        "model_performance": [],
        "system_availability": [],
    }

    # 1. Rollup Timeseries
    for _ in range(iterations):
        t0 = time.perf_counter()
        engine.get_incident_timeseries(filt, bucket_interval="1d", use_rollup=True)
        results["rollup_timeseries"].append((time.perf_counter() - t0) * 1000.0)

    # 2. Raw Timeseries
    for _ in range(iterations):
        t0 = time.perf_counter()
        engine.get_incident_timeseries(filt, bucket_interval="1d", use_rollup=False)
        results["raw_timeseries"].append((time.perf_counter() - t0) * 1000.0)

    # 3. Incident Summary
    for _ in range(iterations):
        t0 = time.perf_counter()
        engine.get_incident_summary(filt)
        results["incident_summary"].append((time.perf_counter() - t0) * 1000.0)

    # 4. Model Performance
    for _ in range(iterations):
        t0 = time.perf_counter()
        engine.get_model_performance(filt)
        results["model_performance"].append((time.perf_counter() - t0) * 1000.0)

    # 5. System Availability
    for _ in range(iterations):
        t0 = time.perf_counter()
        engine.get_system_availability(filt)
        results["system_availability"].append((time.perf_counter() - t0) * 1000.0)

    summary: dict[str, dict[str, float]] = {}
    for name, latencies in results.items():
        sorted_lat = sorted(latencies)
        p95_idx = int(0.95 * len(sorted_lat))
        summary[name] = {
            "min_ms": round(min(latencies), 3),
            "median_ms": round(statistics.median(latencies), 3),
            "mean_ms": round(statistics.mean(latencies), 3),
            "p95_ms": round(sorted_lat[p95_idx], 3),
            "max_ms": round(max(latencies), 3),
        }
    return summary


def run_smoke_test() -> None:
    print("=" * 70)
    print(" Sentinel-AI Phase 5A Smoke Test & Analytics Latency Benchmark")
    print("=" * 70)

    import gc

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "smoke_analytics.db"

        print(f"\n[1/5] Applying Database Migrations to: {db_path.name}")
        runner = MigrationRunner(db_path)
        runner.run()

        repo = IncidentRepository(
            db_path,
            GovernanceConfig(merge_window_seconds=120, writer_queue_size=64, evidence_root=str(Path(tmp_dir) / "evidence"))
        )

        print("[2/5] Seeding 30-day synthetic telemetry and incidents...")
        seed_synthetic_dataset(db_path)

        engine = AnalyticsEngine(repo)

        print("[3/5] Executing Incremental Daily Rollup Job...")
        r_info = engine.run_rollup(force_full=True)
        print(f"      Rollup completed: {r_info['daily_rows_inserted']} daily rows, {r_info['device_rows_inserted']} device rows")
        print(f"      High-water mark: {r_info['high_water_mark']}")

        filt = AnalyticsFilter(
            start_time="2026-09-01T00:00:00+00:00",
            end_time="2026-09-30T23:59:59+00:00"
        )

        print("[4/5] Verifying Analytics Queries & Response Envelopes...")

        # A. Summary
        summary = engine.get_incident_summary(filt)
        try:
            assert summary["empty_state"] is False
            assert summary["total_incidents"] == 120
            assert summary["mean_acknowledgment_seconds"] is not None
            assert summary["median_acknowledgment_seconds"] is not None
            assert summary["p95_acknowledgment_seconds"] is not None
            assert summary["false_alarm_count"] == 20
            print(f"      [PASS] Summary: 120 incidents, MTTA={summary['mean_acknowledgment_seconds']}s (p95={summary['p95_acknowledgment_seconds']}s), False Alarms={summary['false_alarm_count']}")

            # B. Model Performance
            perf = engine.get_model_performance(filt)
            assert perf["total_predictions"] == 80
            assert perf["evaluated_predictions"] == 50
            assert perf["accuracy"] is not None
            assert perf["disagreement_rate_pct"] is not None
            print(f"      [PASS] Model Perf: 80 predictions, Accuracy={perf['accuracy']*100:.1f}%, Disagreement={perf['disagreement_rate_pct']}%, OOD={perf['ood_rate']*100:.1f}%")

            # C. Drift Analytics
            drift = engine.get_drift_analytics(filt)
            assert drift["total_snapshots"] == 15
            print(f"      [PASS] Drift: 15 snapshots across 30 days, latest status={drift['latest_status_by_model']['edge-vision-v1']['status']}")

            # D. Availability
            avail = engine.get_system_availability(filt)
            assert "camera" in avail["components"]
            assert "audio" in avail["components"]
            print(f"      [PASS] Availability: Camera={avail['components']['camera']['availability_pct']}%, Audio={avail['components']['audio']['availability_pct']}%")

            # E. Outbox History
            outbox_data = engine.get_outbox_analytics(filt)
            assert outbox_data["counts"]["SYNCED"] == 20
            assert outbox_data["counts"]["PENDING"] == 8
            print(f"      [PASS] Outbox History: {outbox_data['counts']['SYNCED']} synced, {outbox_data['counts']['PENDING']} pending backlog")

            # F. Paginated Drill-Down
            page1 = engine.get_paginated_incidents(filt, page=1, page_size=25)
            assert len(page1["items"]) == 25
            assert page1["total_items"] == 120
            print(f"      [PASS] Drill-down: Page 1/5 loaded ({len(page1['items'])} items)")

            print("\n[5/5] Running Performance Latency Benchmark (50 iterations each)...")
            bench = benchmark_helper(engine, filt, iterations=50)

            print("-" * 70)
            print(f"{'Query Target':<25} | {'Min (ms)':<9} | {'Median (ms)':<11} | {'p95 (ms)':<9} | {'Mean (ms)':<9}")
            print("-" * 70)
            for target, stats in bench.items():
                print(f"{target:<25} | {stats['min_ms']:<9.3f} | {stats['median_ms']:<11.3f} | {stats['p95_ms']:<9.3f} | {stats['mean_ms']:<9.3f}")
            print("-" * 70)

            assert bench["rollup_timeseries"]["p95_ms"] < 25.0, f"Rollup latency exceeded limit: {bench['rollup_timeseries']['p95_ms']}ms"
            print("\n[SUCCESS] All Phase 5A smoke checks and latency benchmarks passed successfully!\n")
        finally:
            repo.close()
            gc.collect()


if __name__ == "__main__":
    run_smoke_test()
