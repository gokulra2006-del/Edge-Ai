from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from src.config.governance_config import GovernanceConfig
from src.modules.database.governed_store import IncidentRepository, MigrationRunner
from src.modules.analytics.analytics_engine import AnalyticsEngine, resolve_window_bounds


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
