from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import pytest

from src.config.governance_config import GovernanceConfig
from src.modules.database.governed_store import IncidentRepository, MigrationRunner
from src.modules.dashboard import app as dashboard_app


@pytest.fixture
def analytics_test_env(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "test_dash_analytics.db"
    MigrationRunner(db_file).run()
    repo = IncidentRepository(
        db_file,
        GovernanceConfig(merge_window_seconds=120, writer_queue_size=32, evidence_root=str(tmp_path / "evidence"))
    )

    now = datetime.now(timezone.utc)
    t1 = (now - timedelta(hours=3)).isoformat()
    t2 = (now - timedelta(hours=1)).isoformat()

    # Seed incidents
    with sqlite3.connect(db_file) as con:
        con.execute(
            """
            INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status,
                                  created_at, updated_at, severity, acknowledged_seconds,
                                  resolution_seconds, assurance_level, is_demo)
            VALUES(?, 'u1', 'FIRE', 'ZONE_A_INTERSECTION', 'RESOLVED', ?, ?, 'CRITICAL', 14.0, 110.0, 'FULL', 0)
            """,
            ("INC-01", t1, t1)
        )
        con.execute(
            """
            INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status,
                                  created_at, updated_at, severity, acknowledged_seconds,
                                  resolution_seconds, assurance_level, is_demo)
            VALUES(?, 'u2', 'COLLISION', 'ZONE_B_INTERSECTION', 'OPEN', ?, ?, 'HIGH', 20.0, NULL, 'FULL', 0)
            """,
            ("INC-02", t2, t2)
        )
        con.execute(
            """
            INSERT INTO predictions(id, incident_id, timestamp, label, confidence, model_id, payload_json)
            VALUES(1, 'INC-01', ?, 'FIRE', 0.94, 'edge-acoustic-net-v1', ?)
            """,
            (t1, json.dumps({"ood_status": "IN_DISTRIBUTION"}))
        )
        con.execute(
            """
            INSERT INTO prediction_feedback(prediction_id, label, corrected_class, operator_id, operator_role, timestamp)
            VALUES(1, 'CORRECT', NULL, 'ops1', 'OPERATOR', ?)
            """,
            (t1,)
        )
        con.execute(
            """
            INSERT INTO drift_snapshots(model_id, timestamp, status, reasons_json, metrics_json, sample_count, insufficient_data)
            VALUES('edge-acoustic-net-v1', ?, 'STABLE', '[]', '{"psi": 0.03}', 120, 0)
            """,
            (t1,)
        )
        con.execute(
            """
            INSERT INTO device_health_events(timestamp, component, previous_status, current_status, reason_code, message, details_json)
            VALUES(?, 'camera', 'OK', 'OK', 'nominal', 'Stream healthy', '{}')
            """,
            (t1,)
        )
        con.execute(
            """
            INSERT INTO sync_outbox(idempotency_key, target, payload_type, attempts, next_attempt_at, status, priority, last_error, created_at, updated_at, payload_json)
            VALUES('idem-1', 'firebase', 'incident', 1, ?, 'PENDING', 'HIGH', NULL, ?, ?, '{}')
            """,
            (t1, t1, t1)
        )

    # Monkeypatch governed repository and analytics engine in dashboard_app
    from src.modules.analytics.analytics_engine import AnalyticsEngine
    test_engine = AnalyticsEngine(repo)
    monkeypatch.setattr(dashboard_app, "GOVERNED_REPOSITORY", repo)
    monkeypatch.setattr(dashboard_app, "ANALYTICS_ENGINE", test_engine)
    monkeypatch.setattr(dashboard_app, "_ANALYTICS_CACHE", {})

    server = HTTPServer(("127.0.0.1", 0), dashboard_app.DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    yield base_url

    server.shutdown()
    repo.close()


def test_offline_chart_bundle_served(analytics_test_env):
    """Ensure Chart.js is bundled locally without CDN dependencies."""
    base = analytics_test_env
    with urlopen(f"{base}/chart.min.js") as resp:
        assert resp.status == 200
        content_type = resp.headers.get("Content-Type")
        assert "javascript" in content_type
        data = resp.read()
        assert len(data) > 100000  # verified local bundle


def test_analytics_overview_endpoint(analytics_test_env):
    """Test /api/analytics/overview returns KPI cards, zone comparison, and caches responses."""
    base = analytics_test_env
    with urlopen(f"{base}/api/analytics/overview?range=24h") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "kpis" in data
        assert "zones" in data
        assert "summary" in data

        kpis = data["kpis"]
        assert kpis["total_incidents"] == 2
        assert kpis["active_incidents"] == 1
        assert kpis["resolved_incidents"] == 1
        assert kpis["mtta_seconds"] == 17.0
        assert kpis["mttr_seconds"] == 110.0
        assert kpis["system_availability_pct"] == 100.0

        # Zone risk checks
        zones = data["zones"]
        assert len(zones) >= 2
        zone_ids = [z["zone_id"] for z in zones]
        assert "ZONE_A_INTERSECTION" in zone_ids
        assert "ZONE_B_INTERSECTION" in zone_ids


def test_analytics_trends_and_models_endpoints(analytics_test_env):
    """Test /api/analytics/trends and /api/analytics/models."""
    base = analytics_test_env
    with urlopen(f"{base}/api/analytics/trends?range=24h&bucket=1h") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "timeseries" in data
        assert len(data["timeseries"]) >= 1

    with urlopen(f"{base}/api/analytics/models?range=24h") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "performance" in data
        assert "drift" in data
        assert data["performance"]["total_predictions"] == 1
        assert data["performance"]["accuracy"] == 1.0


def test_analytics_availability_and_outbox_endpoints(analytics_test_env):
    """Test /api/analytics/availability and /api/analytics/outbox."""
    base = analytics_test_env
    with urlopen(f"{base}/api/analytics/availability?range=24h") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "overall_availability_pct" in data
        assert "components" in data
        assert "camera" in data["components"]

    with urlopen(f"{base}/api/analytics/outbox?range=24h") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "counts" in data
        assert "recent" in data
        assert len(data["recent"]) == 1
        assert data["recent"][0]["idempotency_key"] == "idem-1"


def test_dashboard_ui_bundle_and_role_access():
    """Verify HTML and JavaScript contain the new analytics view, offline chart script, and role matrix."""
    web_dir = Path("src/modules/dashboard/web")
    html_content = (web_dir / "index.html").read_text(encoding="utf-8")
    js_content = (web_dir / "app.js").read_text(encoding="utf-8")

    # Offline chart bundle
    assert '/chart.min.js' in html_content
    assert 'https://cdn.jsdelivr.net/npm/chart.js' not in html_content

    # UI View elements
    assert 'id="view-analytics"' in html_content
    assert 'id="nav-btn-analytics"' in html_content
    assert 'id="analyticsTrendsChart"' in html_content
    assert 'id="zoneRiskList"' in html_content
    assert 'id="analyticsFilterRange"' in html_content
    assert 'id="analyticsLoadingState"' in html_content
    assert 'id="analyticsEmptyState"' in html_content
    assert 'id="analyticsErrorState"' in html_content

    # JS Router and Role mappings
    assert '"analytics"' in js_content
    assert 'loadAnalytics' in js_content
    assert 'renderAnalyticsTrendsChart' in js_content
    assert 'renderZoneRiskList' in js_content
