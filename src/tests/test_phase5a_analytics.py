from __future__ import annotations

import json
import sqlite3
import statistics
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from src.config.governance_config import GovernanceConfig
from src.modules.database.governed_store import IncidentRepository, MigrationRunner
from src.modules.analytics.analytics_engine import AnalyticsEngine, resolve_window_bounds
from src.modules.analytics.filters import AnalyticsFilter
from src.modules.analytics.rollup_engine import RollupEngine


@pytest.fixture
def test_repo(tmp_path: Path):
    db_file = tmp_path / "test_analytics.db"
    MigrationRunner(db_file).run()
    repo = IncidentRepository(
        db_file,
        GovernanceConfig(merge_window_seconds=120, writer_queue_size=32, evidence_root=str(tmp_path / "evidence"))
    )
    yield repo
    repo.close()


def test_window_resolution():
    now = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
    s24, e24 = resolve_window_bounds("24h", ref_time=now)
    assert s24 == (now - timedelta(hours=24)).isoformat()
    assert e24 == now.isoformat()

    s7d, e7d = resolve_window_bounds("7d", ref_time=now)
    assert s7d == (now - timedelta(days=7)).isoformat()

    s30d, e30d = resolve_window_bounds("30d", ref_time=now)
    assert s30d == (now - timedelta(days=30)).isoformat()

    s_all, e_all = resolve_window_bounds("all", ref_time=now)
    assert s_all.startswith("1970")

    # Explicit timestamps override window
    s_exp, e_exp = resolve_window_bounds("24h", start_time="2026-10-01T00:00:00Z", end_time="2026-10-02T00:00:00Z")
    assert s_exp == "2026-10-01T00:00:00Z"
    assert e_exp == "2026-10-02T00:00:00Z"


def test_incident_summary_and_timeseries(test_repo):
    engine = AnalyticsEngine(test_repo)
    now = datetime.now(timezone.utc)
    t1 = (now - timedelta(hours=5)).isoformat()
    t2 = (now - timedelta(hours=2)).isoformat()

    # Populate incidents
    with sqlite3.connect(test_repo.db_path) as con:
        con.execute(
            """
            INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status,
                                  created_at, updated_at, severity, acknowledged_seconds,
                                  resolution_seconds, assurance_level, is_demo)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("INC-01", "u1", "FIRE", "ZONE_A", "RESOLVED", t1, t1, "CRITICAL", 12.5, 120.0, "FULL", 0)
        )
        con.execute(
            """
            INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status,
                                  created_at, updated_at, severity, acknowledged_seconds,
                                  resolution_seconds, assurance_level, is_demo)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("INC-02", "u2", "COLLISION", "ZONE_B", "FALSE_ALARM", t2, t2, "HIGH", 8.5, 45.0, "VISION_ONLY", 0)
        )
        con.execute(
            """
            INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status,
                                  created_at, updated_at, severity, acknowledged_seconds,
                                  resolution_seconds, assurance_level, is_demo)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("INC-DEMO", "u3", "TEST", "ZONE_A", "NEW", t2, t2, "LOW", None, None, "FULL", 1)
        )

    summary = engine.get_incident_summary(window="24h", include_demo=False)
    assert summary["total_incidents"] == 2
    assert summary["by_status"]["RESOLVED"] == 1
    assert summary["by_status"]["FALSE_ALARM"] == 1
    assert summary["by_severity"]["CRITICAL"] == 1
    assert summary["by_severity"]["HIGH"] == 1
    assert summary["by_event_type"]["FIRE"] == 1
    assert summary["by_zone"]["ZONE_A"] == 1
    assert summary["by_assurance_level"]["FULL"] == 1
    assert summary["by_assurance_level"]["VISION_ONLY"] == 1
    assert summary["false_alarm_count"] == 1
    assert summary["demo_count"] == 1
    assert summary["mean_acknowledgment_seconds"] == 10.5
    assert summary["mean_resolution_seconds"] == 82.5

    # With demo included
    summary_with_demo = engine.get_incident_summary(window="24h", include_demo=True)
    assert summary_with_demo["total_incidents"] == 3

    # Timeseries check
    ts = engine.get_incident_timeseries(window="24h", bucket_interval="1h", include_demo=False)
    assert len(ts) >= 1
    total_in_ts = sum(b["total"] for b in ts)
    assert total_in_ts == 2


def test_model_performance_and_confusion_matrix(test_repo):
    engine = AnalyticsEngine(test_repo)
    now = datetime.now(timezone.utc)
    t1 = (now - timedelta(hours=3)).isoformat()
    t2 = (now - timedelta(hours=1)).isoformat()

    with sqlite3.connect(test_repo.db_path) as con:
        # Predictions
        con.execute(
            """
            INSERT INTO predictions(id, incident_id, timestamp, label, confidence, model_id, payload_json)
            VALUES(1, 'INC-01', ?, 'FIRE', 0.95, 'edge-fire-v1', ?)
            """,
            (t1, json.dumps({"ood_status": "IN_DISTRIBUTION"}))
        )
        con.execute(
            """
            INSERT INTO predictions(id, incident_id, timestamp, label, confidence, model_id, payload_json)
            VALUES(2, 'INC-01', ?, 'COLLISION', 0.70, 'edge-collision-v1', ?)
            """,
            (t2, json.dumps({"ood_status": "OOD"}))
        )
        # Feedback: prediction 1 is CORRECT, prediction 2 is INCORRECT with corrected_class = 'NORMAL'
        con.execute(
            """
            INSERT INTO prediction_feedback(prediction_id, label, corrected_class, operator_id, operator_role, timestamp, comment)
            VALUES(1, 'CORRECT', NULL, 'op1', 'OPERATOR', ?, 'Confirmed fire')
            """,
            (t1,)
        )
        con.execute(
            """
            INSERT INTO prediction_feedback(prediction_id, label, corrected_class, operator_id, operator_role, timestamp, comment)
            VALUES(2, 'INCORRECT', 'NORMAL', 'op1', 'OPERATOR', ?, 'Was clear street')
            """,
            (t2,)
        )

    perf = engine.get_model_performance(window="24h")
    assert perf["total_predictions"] == 2
    assert perf["evaluated_predictions"] == 2
    assert perf["correct_predictions"] == 1
    assert perf["incorrect_predictions"] == 1
    assert perf["accuracy"] == 0.5
    assert perf["ood_prediction_count"] == 1
    assert perf["ood_rate"] == 0.5
    assert perf["false_alarm_rate"] == 0.5
    assert perf["mean_confidence"] == 0.825

    # Check confusion matrix: Actual 'FIRE' predicted 'FIRE' = 1; Actual 'NORMAL' predicted 'COLLISION' = 1
    matrix = perf["confusion_matrix"]
    assert matrix["FIRE"]["FIRE"] == 1
    assert matrix["NORMAL"]["COLLISION"] == 1

    # Check by_model
    assert "edge-fire-v1" in perf["by_model"]
    assert perf["by_model"]["edge-fire-v1"]["accuracy"] == 1.0
    assert "edge-collision-v1" in perf["by_model"]
    assert perf["by_model"]["edge-collision-v1"]["accuracy"] == 0.0


def test_drift_analytics(test_repo):
    engine = AnalyticsEngine(test_repo)
    now = datetime.now(timezone.utc)
    t1 = (now - timedelta(hours=4)).isoformat()
    t2 = (now - timedelta(hours=1)).isoformat()

    with sqlite3.connect(test_repo.db_path) as con:
        con.execute(
            """
            INSERT INTO drift_snapshots(model_id, timestamp, status, reasons_json, metrics_json, sample_count, insufficient_data)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            ("m_audio", t1, "STABLE", json.dumps([]), json.dumps({"psi": 0.04}), 100, 0)
        )
        con.execute(
            """
            INSERT INTO drift_snapshots(model_id, timestamp, status, reasons_json, metrics_json, sample_count, insufficient_data)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            ("m_audio", t2, "DRIFT_WARNING", json.dumps(["psi_high"]), json.dumps({"psi": 0.28}), 120, 0)
        )

    drift = engine.get_drift_analytics(window="24h")
    assert drift["total_snapshots"] == 2
    assert drift["status_distribution"]["STABLE"] == 1
    assert drift["status_distribution"]["DRIFT_WARNING"] == 1
    assert drift["latest_status_by_model"]["m_audio"]["status"] == "DRIFT_WARNING"
    assert len(drift["psi_progression"]) == 2
    assert drift["psi_progression"][1]["psi"] == 0.28


def test_system_availability_and_operator_analytics(test_repo):
    engine = AnalyticsEngine(test_repo)
    now = datetime.now(timezone.utc)
    t1 = (now - timedelta(hours=6)).isoformat()
    t2 = (now - timedelta(hours=3)).isoformat()

    with sqlite3.connect(test_repo.db_path) as con:
        con.execute(
            """
            INSERT INTO device_health_events(timestamp, component, previous_status, current_status, reason_code, message, details_json)
            VALUES(?, 'camera', 'OK', 'DEGRADED', 'fps_low', 'Frame rate dropped', '{}')
            """,
            (t1,)
        )
        con.execute(
            """
            INSERT INTO device_health_events(timestamp, component, previous_status, current_status, reason_code, message, details_json)
            VALUES(?, 'microphone', 'OK', 'OK', 'normal', 'Audio healthy', '{}')
            """,
            (t2,)
        )
        con.execute(
            """
            INSERT INTO operator_actions(incident_id, timestamp, operator_id, action, approved, payload_json)
            VALUES('INC-01', ?, 'cmd_jane', 'dispatch_fire', 1, '{}')
            """,
            (t1,)
        )
        con.execute(
            """
            INSERT INTO incident_notes(incident_id, timestamp, operator_id, operator_role, note)
            VALUES('INC-01', ?, 'cmd_jane', 'COMMANDER', 'Dispatched unit 4')
            """,
            (t2,)
        )

    avail = engine.get_system_availability(window="24h")
    assert avail["overall_availability_pct"] == 100.0  # both DEGRADED and OK are available
    assert "camera" in avail["components"]
    assert avail["components"]["camera"]["degraded_events"] == 1

    op_data = engine.get_operator_analytics(window="24h")
    assert op_data["total_actions"] == 1
    assert op_data["approved_actions"] == 1
    assert "cmd_jane" in op_data["by_operator"]
    assert op_data["by_operator"]["cmd_jane"]["actions"] == 1
    assert op_data["by_operator"]["cmd_jane"]["notes_count"] == 1


def test_pagination_and_query_limits(test_repo):
    engine = AnalyticsEngine(test_repo)
    now = datetime.now(timezone.utc)

    # Insert 25 dummy incidents
    with sqlite3.connect(test_repo.db_path) as con:
        for i in range(25):
            t = (now - timedelta(minutes=i * 2)).isoformat()
            con.execute(
                """
                INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at, severity, is_demo)
                VALUES(?, ?, 'TEST', 'ZONE_A', 'NEW', ?, ?, 'LOW', 0)
                """,
                (f"INC-{i:03d}", f"uuid-{i}", t, t)
            )

    # Page 1 (limit 10)
    p1 = engine.get_paginated_incidents(page=1, page_size=10, window="24h")
    assert p1["page"] == 1
    assert p1["page_size"] == 10
    assert p1["total_items"] == 25
    assert p1["total_pages"] == 3
    assert len(p1["items"]) == 10
    assert p1["items"][0]["incident_id"] == "INC-000"

    # Page 3 (remaining 5)
    p3 = engine.get_paginated_incidents(page=3, page_size=10, window="24h")
    assert len(p3["items"]) == 5

    # Page clamp bounds
    p_clamp = engine.get_paginated_incidents(page=-5, page_size=999, window="24h")
    assert p_clamp["page"] == 1
    assert p_clamp["page_size"] == 200  # Clamped to max 200

    # Paginated predictions
    with sqlite3.connect(test_repo.db_path) as con:
        con.execute(
            "INSERT INTO predictions(id, incident_id, timestamp, label, confidence, model_id, payload_json) VALUES(100, 'INC-000', ?, 'FIRE', 0.9, 'm1', '{}')",
            (now.isoformat(),)
        )
    preds = engine.get_paginated_predictions(page=1, page_size=10, window="24h")
    assert preds["total_items"] == 1
    assert preds["items"][0]["id"] == 100


def test_read_only_concurrency_with_active_writer(test_repo):
    """Ensure AnalyticsEngine can read concurrently without blocking or failing during SQLite writes."""
    from src.modules.database.governed_store import utc_now
    engine = AnalyticsEngine(test_repo)

    # Spawn background writes via test_repo.writer
    for i in range(10):
        test_repo.writer.submit(
            lambda c, idx=i: c.execute(
                "INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at, is_demo) VALUES(?, ?, 'hazard', 'Z1', 'OPEN', ?, ?, 0)",
                (f"INC-CONC-{idx:03d}", f"uuid-{idx}", utc_now(), utc_now())
            )
        )

    # Immediately query summary without waiting for drain
    summary = engine.get_incident_summary(window="24h")
    assert isinstance(summary["total_incidents"], int)

    # Drain and verify count updated
    test_repo.writer.drain()
    summary_drained = engine.get_incident_summary(window="24h")
    assert summary_drained["total_incidents"] == 10


def test_synthetic_30_day_dataset_and_hand_computed_metrics(tmp_path: Path):
    """
    Seed 30 days of synthetic data across 4 zones, all severities, known durations,
    device transitions, operator disagreements, and drift snapshots.
    Verify every metric against hand-computed expected values.
    """
    db_file = tmp_path / "synthetic_30d.db"
    MigrationRunner(db_file).run()
    repo = IncidentRepository(
        db_file,
        GovernanceConfig(merge_window_seconds=120, writer_queue_size=64, evidence_root=str(tmp_path / "evidence"))
    )

    base_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    zones = ["ZONE_NORTH", "ZONE_SOUTH", "ZONE_EAST", "ZONE_WEST"]
    severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    event_types = ["FIRE", "COLLISION", "HAZARD", "NEAR_MISS"]

    total_incidents = 60
    false_alarm_count = 12
    ack_durations = [10.0, 20.0, 30.0, 40.0, 50.0] * 12  # 60 items
    resolve_durations = [100.0, 150.0, 200.0, 250.0] * 15  # 60 items

    actual_res_durations = [resolve_durations[i] for i in range(total_incidents) if (i < false_alarm_count or i % 2 == 0)]
    expected_mean_ack = round(statistics.mean(ack_durations), 2)  # 30.0
    expected_median_ack = round(statistics.median(ack_durations), 2)  # 30.0
    expected_mean_res = round(statistics.mean(actual_res_durations), 2)  # 158.33
    expected_median_res = round(statistics.median(actual_res_durations), 2)  # 150.0
    expected_far_rate = round((false_alarm_count / total_incidents) * 100.0, 2)  # 20.0

    with sqlite3.connect(db_file) as con:
        # 1. Insert 60 incidents evenly spaced over 30 days
        for i in range(total_incidents):
            day_offset = i % 30
            dt = base_date + timedelta(days=day_offset, hours=i % 24, minutes=10)
            iso = dt.isoformat()
            zone = zones[i % len(zones)]
            sev = severities[i % len(severities)]
            ev_type = event_types[i % len(event_types)]
            status = "FALSE_ALARM" if i < false_alarm_count else ("RESOLVED" if i % 2 == 0 else "OPEN")
            ack = ack_durations[i]
            res = resolve_durations[i] if status in ("RESOLVED", "FALSE_ALARM") else None

            con.execute(
                """
                INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status,
                                      created_at, updated_at, severity, acknowledged_seconds,
                                      resolution_seconds, assurance_level, is_demo)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'FULL', 0)
                """,
                (f"INC-SYN-{i:03d}", f"uuid-syn-{i}", ev_type, zone, status, iso, iso, sev, ack, res)
            )

        # 2. Insert 40 predictions
        # 30 with 0.90 confidence, 10 with 0.70 confidence -> sum = 27.0 + 7.0 = 34.0, mean = 0.85
        # 8 with OOD -> ood_rate = 8 / 40 = 0.20 (20.0%)
        for i in range(40):
            dt = base_date + timedelta(days=i % 30, hours=12)
            iso = dt.isoformat()
            conf = 0.90 if i < 30 else 0.70
            is_ood = (i < 8)
            payload = json.dumps({"ood_status": "OOD" if is_ood else "IN_DISTRIBUTION"})
            con.execute(
                """
                INSERT INTO predictions(id, incident_id, timestamp, label, confidence, model_id, payload_json)
                VALUES(?, ?, ?, 'HAZARD', ?, 'm_edge_v1', ?)
                """,
                (i + 1, f"INC-SYN-{i:03d}", iso, conf, payload)
            )

        # 3. Insert 30 prediction feedback records
        # 21 CORRECT, 9 INCORRECT -> evaluated = 30, correct = 21, accuracy = 0.70 (70.0%), disagreement = 9 / 30 = 0.30 (30.0%)
        for i in range(30):
            dt = base_date + timedelta(days=i % 30, hours=13)
            iso = dt.isoformat()
            label = "CORRECT" if i < 21 else "INCORRECT"
            corrected = None if label == "CORRECT" else "NORMAL"
            con.execute(
                """
                INSERT INTO prediction_feedback(prediction_id, label, corrected_class, operator_id, operator_role, timestamp)
                VALUES(?, ?, ?, 'op_alice', 'OPERATOR', ?)
                """,
                (i + 1, label, corrected, iso)
            )

        # 4. Insert 10 drift snapshots
        # 7 STABLE, 2 DRIFT_WARNING, 1 DRIFT_DETECTED
        drift_statuses = ["STABLE"] * 7 + ["DRIFT_WARNING"] * 2 + ["DRIFT_DETECTED"] * 1
        for i, st in enumerate(drift_statuses):
            dt = base_date + timedelta(days=i * 3, hours=14)
            iso = dt.isoformat()
            psi = 0.02 if st == "STABLE" else (0.18 if st == "DRIFT_WARNING" else 0.35)
            con.execute(
                """
                INSERT INTO drift_snapshots(model_id, timestamp, status, reasons_json, metrics_json, sample_count, insufficient_data)
                VALUES('m_edge_v1', ?, ?, '[]', ?, 150, 0)
                """,
                (iso, st, json.dumps({"psi": psi}))
            )

        # 5. Insert device health events
        # Camera stays OK/DEGRADED across 30 days
        con.execute(
            """
            INSERT INTO device_health_events(timestamp, component, previous_status, current_status, reason_code, message, details_json)
            VALUES(?, 'camera', 'OK', 'OK', 'nominal', 'healthy', '{}')
            """,
            (base_date.isoformat(),)
        )
        # Audio has an outage event on day 15
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
            ((base_date + timedelta(days=15)).isoformat(),)
        )

    engine = AnalyticsEngine(repo)
    # Run rollup over the 30-day range
    rollup_res = engine.run_rollup(force_full=True)
    assert rollup_res["daily_rows_inserted"] > 0

    filt = AnalyticsFilter(
        start_time="2026-09-01T00:00:00+00:00",
        end_time="2026-09-30T23:59:59+00:00"
    )

    # 1. Verify Incident Summary Metrics against hand-computed values
    summary = engine.get_incident_summary(filt)
    assert summary["empty_state"] is False
    assert summary["total_incidents"] == 60
    assert summary["false_alarm_count"] == 12
    assert summary["false_alarm_rate_pct"] == expected_far_rate
    assert summary["mean_acknowledgment_seconds"] == expected_mean_ack
    assert summary["median_acknowledgment_seconds"] == expected_median_ack
    assert summary["p95_acknowledgment_seconds"] is not None
    assert summary["mean_resolution_seconds"] == expected_mean_res
    assert summary["median_resolution_seconds"] == expected_median_res

    # 2. Verify Model Performance Metrics against hand-computed values
    perf = engine.get_model_performance(filt)
    assert perf["empty_state"] is False
    assert perf["total_predictions"] == 40
    assert perf["evaluated_predictions"] == 30
    assert perf["correct_predictions"] == 21
    assert perf["incorrect_predictions"] == 9
    assert perf["accuracy"] == 0.70
    assert perf["disagreement_rate_pct"] == 30.0
    assert perf["ood_rate"] == 0.20
    assert perf["mean_confidence"] == 0.85
    assert len(perf["trends"]) > 0

    # 3. Verify Drift Snapshot History
    drift = engine.get_drift_analytics(filt)
    assert drift["empty_state"] is False
    assert drift["total_snapshots"] == 10
    assert drift["status_distribution"]["STABLE"] == 7
    assert drift["status_distribution"]["DRIFT_WARNING"] == 2
    assert drift["status_distribution"]["DRIFT_DETECTED"] == 1
    assert len(drift["psi_progression"]) == 10

    # 4. Verify System Availability & Missing Data Handling
    avail = engine.get_system_availability(filt)
    assert "camera" in avail["components"]
    assert "audio" in avail["components"]
    # Audio experienced downtime, so availability must be < 100%
    assert avail["components"]["audio"]["availability_pct"] < 100.0

    repo.close()


def test_edge_cases_and_filter_boundaries(tmp_path: Path):
    """
    Cover edge cases:
    - Empty range returns empty_state=True with no ZeroDivisionError.
    - Single day range bounds properly.
    - Zero denominators handled gracefully.
    - Timezone/day boundaries correctly partitioned.
    """
    db_file = tmp_path / "edge_cases.db"
    MigrationRunner(db_file).run()
    repo = IncidentRepository(
        db_file,
        GovernanceConfig(merge_window_seconds=120, writer_queue_size=32, evidence_root=str(tmp_path / "evidence"))
    )

    with sqlite3.connect(db_file) as con:
        # Boundary event 1: 23:59:59 on 2026-09-10
        con.execute(
            """
            INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at, severity, is_demo)
            VALUES('INC-B1', 'u-b1', 'HAZARD', 'Z1', 'OPEN', '2026-09-10T23:59:59+00:00', '2026-09-10T23:59:59+00:00', 'HIGH', 0)
            """
        )
        # Boundary event 2: 00:00:01 on 2026-09-11
        con.execute(
            """
            INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at, severity, is_demo)
            VALUES('INC-B2', 'u-b2', 'HAZARD', 'Z1', 'OPEN', '2026-09-11T00:00:01+00:00', '2026-09-11T00:00:01+00:00', 'HIGH', 0)
            """
        )

    engine = AnalyticsEngine(repo)

    # 1. Empty range test
    empty_filt = AnalyticsFilter(
        start_time="2025-01-01T00:00:00+00:00",
        end_time="2025-01-05T00:00:00+00:00"
    )
    empty_summary = engine.get_incident_summary(empty_filt)
    assert empty_summary["empty_state"] is True
    assert empty_summary["total_incidents"] == 0
    assert empty_summary["false_alarm_rate_pct"] == 0.0
    assert empty_summary["mean_acknowledgment_seconds"] is None

    empty_perf = engine.get_model_performance(empty_filt)
    assert empty_perf["empty_state"] is True
    assert empty_perf["accuracy"] is None
    assert empty_perf["disagreement_rate_pct"] == 0.0

    # 2. Single day range test
    single_day_filt = AnalyticsFilter(
        start_time="2026-09-10T00:00:00+00:00",
        end_time="2026-09-10T23:59:59+00:00"
    )
    single_summary = engine.get_incident_summary(single_day_filt)
    assert single_summary["total_incidents"] == 1
    assert single_summary["empty_state"] is False

    # 3. Day boundary test
    ts = engine.get_incident_timeseries(
        start_time="2026-09-10T00:00:00+00:00",
        end_time="2026-09-11T23:59:59+00:00",
        bucket_interval="1d",
        use_rollup=False
    )
    assert len(ts) == 2
    assert ts[0]["bucket"] == "2026-09-10T00:00:00Z" and ts[0]["total"] == 1
    assert ts[1]["bucket"] == "2026-09-11T00:00:00Z" and ts[1]["total"] == 1

    repo.close()


def test_late_data_and_rollup_idempotence(tmp_path: Path):
    """
    Verify incremental rollup handles late-arriving data by re-rolling N days back,
    and verify multiple re-runs are completely idempotent.
    """
    db_file = tmp_path / "late_data.db"
    MigrationRunner(db_file).run()
    repo = IncidentRepository(
        db_file,
        GovernanceConfig(merge_window_seconds=120, writer_queue_size=32, evidence_root=str(tmp_path / "evidence"))
    )
    engine = AnalyticsEngine(repo)

    # Day 1 & Day 2 initial data
    with sqlite3.connect(db_file) as con:
        con.execute(
            "INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at, severity, is_demo) VALUES('INC-1', 'u1', 'FIRE', 'Z1', 'OPEN', '2026-10-01T10:00:00+00:00', '2026-10-01T10:00:00+00:00', 'CRITICAL', 0)"
        )
        con.execute(
            "INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at, severity, is_demo) VALUES('INC-2', 'u2', 'FIRE', 'Z1', 'OPEN', '2026-10-02T10:00:00+00:00', '2026-10-02T10:00:00+00:00', 'CRITICAL', 0)"
        )

    # Initial rollup
    r1 = engine.run_rollup(force_full=True)
    assert r1["daily_rows_inserted"] == 2

    # Late arriving incident for Day 1
    with sqlite3.connect(db_file) as con:
        con.execute(
            "INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at, severity, is_demo) VALUES('INC-LATE', 'u3', 'FIRE', 'Z1', 'OPEN', '2026-10-01T15:00:00+00:00', '2026-10-01T15:00:00+00:00', 'CRITICAL', 0)"
        )

    # Re-run rollup with days_back=3
    r2 = engine.run_rollup(days_back=3)

    with sqlite3.connect(db_file) as con:
        d1_row = con.execute("SELECT total_incidents FROM analytics_daily WHERE day='2026-10-01'").fetchone()
        assert d1_row[0] == 2  # Captured the late incident!

    # Idempotence test: run rollup again without changes
    r3 = engine.run_rollup(days_back=3)
    with sqlite3.connect(db_file) as con:
        d1_row_re = con.execute("SELECT total_incidents FROM analytics_daily WHERE day='2026-10-01'").fetchone()
        assert d1_row_re[0] == 2  # Remains exactly 2

    repo.close()


def test_rollup_vs_raw_query_equality(tmp_path: Path):
    """Verify metrics queried from rollup table match raw query aggregations."""
    db_file = tmp_path / "equality.db"
    MigrationRunner(db_file).run()
    repo = IncidentRepository(
        db_file,
        GovernanceConfig(merge_window_seconds=120, writer_queue_size=32, evidence_root=str(tmp_path / "evidence"))
    )

    with sqlite3.connect(db_file) as con:
        for d in range(1, 6):
            for i in range(4):
                dt = f"2026-10-0{d}T1{i}:00:00+00:00"
                sev = "CRITICAL" if i == 0 else "LOW"
                st = "FALSE_ALARM" if i == 1 else "RESOLVED"
                con.execute(
                    """
                    INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at, severity, is_demo)
                    VALUES(?, ?, 'TEST', 'Z1', ?, ?, ?, ?, 0)
                    """,
                    (f"INC-{d}-{i}", f"u-{d}-{i}", st, dt, dt, sev)
                )

    engine = AnalyticsEngine(repo)
    engine.run_rollup(force_full=True)

    filt = AnalyticsFilter(start_time="2026-10-01T00:00:00+00:00", end_time="2026-10-05T23:59:59+00:00")

    ts_rollup = engine.get_incident_timeseries(filt, bucket_interval="1d", use_rollup=True)
    ts_raw = engine.get_incident_timeseries(filt, bucket_interval="1d", use_rollup=False)

    assert len(ts_rollup) == 5
    assert len(ts_raw) == 5

    for r_roll, r_raw in zip(ts_rollup, ts_raw):
        assert r_roll["bucket"] == r_raw["bucket"]
        assert r_roll["total"] == r_raw["total"]
        assert r_roll["critical"] == r_raw["critical"]
        assert r_roll["false_alarm"] == r_raw["false_alarm"]

    repo.close()


def test_filter_object_validation_rules():
    """Verify AnalyticsFilter validation and error handling."""
    # Valid
    f = AnalyticsFilter(start_time="2026-09-01T00:00:00+00:00", end_time="2026-09-30T00:00:00+00:00", severity="CRITICAL")
    assert f.severity == "CRITICAL"

    # Inverted range
    with pytest.raises(ValueError, match="cannot be after end_time"):
        AnalyticsFilter(start_time="2026-09-30T00:00:00+00:00", end_time="2026-09-01T00:00:00+00:00")

    # Range exceeding 365 days
    with pytest.raises(ValueError, match="exceeds maximum allowed limit"):
        AnalyticsFilter(start_time="2024-01-01T00:00:00+00:00", end_time="2026-01-01T00:00:00+00:00")

    # Invalid severity
    with pytest.raises(ValueError, match="Invalid severity"):
        AnalyticsFilter(start_time="2026-09-01T00:00:00+00:00", end_time="2026-09-10T00:00:00+00:00", severity="INVALID_SEV")
