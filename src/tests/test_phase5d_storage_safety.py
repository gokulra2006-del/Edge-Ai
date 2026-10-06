"""Tests for Phase 5D: Production Data Retention, Storage Safety, WAL Management, and Outbox Resilience."""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
import pytest

from src.modules.database.governed_store import IncidentRepository, MigrationRunner, utc_now
from src.modules.storage.storage_safety import (
    StorageRetentionEngine,
    WalCheckpointManager,
    StorageSafetyStatus,
)
from src.modules.assurance.device_health import HealthMonitor, OfflineSyncOutbox


@pytest.fixture
def storage_env(tmp_path):
    """Sets up an isolated database, storage directories, and repositories."""
    db_path = tmp_path / "test_storage.db"
    base_dir = tmp_path / "app"
    base_dir.mkdir(parents=True, exist_ok=True)

    archives_dir = base_dir / "data" / "archives"
    dvr_dir = base_dir / "data" / "recordings"
    evidence_dir = base_dir / "data" / "evidence"
    reports_dir = base_dir / "reports"
    logs_dir = base_dir / "logs"

    for d in (archives_dir, dvr_dir, evidence_dir, reports_dir, logs_dir):
        d.mkdir(parents=True, exist_ok=True)

    repo = IncidentRepository(db_path=db_path)

    # Initialize telemetry_logs table in test database
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                node_id TEXT NOT NULL,
                audio_class TEXT,
                audio_confidence REAL,
                vision_class TEXT,
                vision_confidence REAL,
                imu_impact INTEGER,
                imu_g_force REAL,
                temperature_c REAL,
                smoke_ppm REAL
            )
            """
        )
        conn.commit()

    config = {
        "storage": {
            "retention": {
                "raw_telemetry_days": 7,
                "archive_telemetry_after_days": 3,
                "dvr_max_bytes": 10000,  # 10 KB for testing cap
                "evidence_retention_days": 30,
                "reports_retention_days": 90,
                "logs_retention_days": 14,
                "synced_outbox_retention_days": 7,
            },
            "wal": {
                "checkpoint_mode": "PASSIVE",
                "auto_truncate_bytes": 5000,
                "checkpoint_interval_seconds": 60,
            },
            "thresholds": {
                "warning_bytes": 1000000,
                "critical_bytes": 200000,
            },
            "paths": {
                "archives_dir": str(archives_dir),
                "dvr_dir": str(dvr_dir),
                "evidence_dir": str(evidence_dir),
                "reports_dir": str(reports_dir),
                "logs_dir": str(logs_dir),
            },
        }
    }

    engine = StorageRetentionEngine(repository=repo, config=config, base_dir=base_dir)

    yield {
        "repo": repo,
        "db_path": db_path,
        "base_dir": base_dir,
        "engine": engine,
        "archives_dir": archives_dir,
        "dvr_dir": dvr_dir,
        "evidence_dir": evidence_dir,
        "reports_dir": reports_dir,
        "logs_dir": logs_dir,
        "config": config,
    }
    repo.close()


def test_telemetry_archival_and_pruning(storage_env):
    """Verify raw telemetry older than cutoff is compressed to gzip archive and pruned, with dry-run safety."""
    repo = storage_env["repo"]
    engine = storage_env["engine"]
    archives_dir = storage_env["archives_dir"]

    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(days=10)).isoformat()
    recent_time = (now - timedelta(days=1)).isoformat()

    # Seed 5 old rows and 3 recent rows
    with sqlite3.connect(str(repo.db_path)) as conn:
        for i in range(5):
            conn.execute(
                "INSERT INTO telemetry_logs(timestamp, node_id, audio_class, audio_confidence) VALUES (?, ?, ?, ?)",
                (old_time, f"node_{i}", "siren", 0.95),
            )
        for i in range(3):
            conn.execute(
                "INSERT INTO telemetry_logs(timestamp, node_id, audio_class, audio_confidence) VALUES (?, ?, ?, ?)",
                (recent_time, f"node_rec_{i}", "normal", 0.1),
            )
        conn.commit()

    # 1. Test Dry-Run: should report 5 rows without pruning or writing archive
    dry_res = engine.archive_telemetry(dry_run=True, older_than_days=3)
    assert dry_res["dry_run"] is True
    assert dry_res["items_inspected"] == 5
    assert dry_res["items_pruned"] == 5
    assert len(list(archives_dir.glob("*.json.gz"))) == 0

    with sqlite3.connect(str(repo.db_path)) as conn:
        count = conn.execute("SELECT count(*) FROM telemetry_logs").fetchone()[0]
        assert count == 8  # Unchanged

    # 2. Test Real Archival Execution
    real_res = engine.archive_telemetry(dry_run=False, older_than_days=3)
    assert real_res["dry_run"] is False
    assert real_res["items_archived"] == 5
    assert real_res["items_pruned"] == 5
    assert real_res["archive_file"] is not None

    archive_file = Path(real_res["archive_file"])
    assert archive_file.exists()
    assert archive_file.name.endswith(".json.gz")

    # Read and verify decompressed gzip content
    with gzip.open(archive_file, "rb") as gz:
        data = json.loads(gz.read().decode("utf-8"))
        assert data["row_count"] == 5
        assert len(data["rows"]) == 5
        assert data["rows"][0]["audio_class"] == "siren"

    # Verify only recent rows remain in database
    with sqlite3.connect(str(repo.db_path)) as conn:
        rem_rows = conn.execute("SELECT * FROM telemetry_logs").fetchall()
        assert len(rem_rows) == 3
        for r in rem_rows:
            assert r[1] == recent_time


def test_dvr_storage_cap_oldest_first_eviction(storage_env):
    """Verify DVR recordings exceeding byte cap are evicted oldest first, preserving newest."""
    engine = storage_env["engine"]
    dvr_dir = storage_env["dvr_dir"]

    # Cap is 10,000 bytes. Create 3 files of 4,000 bytes each (total 12,000 bytes).
    f1 = dvr_dir / "clip_20261001_oldest.mp4"
    f2 = dvr_dir / "clip_20261002_middle.mp4"
    f3 = dvr_dir / "clip_20261003_newest.mp4"

    f1.write_bytes(b"A" * 4000)
    f2.write_bytes(b"B" * 4000)
    f3.write_bytes(b"C" * 4000)

    # Set artificial mtimes: f1 oldest, f3 newest
    now = time.time()
    os.utime(f1, (now - 300, now - 300))
    os.utime(f2, (now - 200, now - 200))
    os.utime(f3, (now - 100, now - 100))

    # Dry-run test: should report f1 to evict, but not delete it
    dry_res = engine.evict_dvr(dry_run=True, max_bytes=10000)
    assert dry_res["dry_run"] is True
    assert dry_res["items_pruned"] == 1
    assert dry_res["bytes_freed"] == 4000
    assert str(f1) in dry_res["evicted_files"]
    assert f1.exists()

    # Real run: f1 must be deleted, f2 and f3 must remain (total 8,000 <= 10,000)
    real_res = engine.evict_dvr(dry_run=False, max_bytes=10000)
    assert real_res["dry_run"] is False
    assert real_res["items_pruned"] == 1
    assert real_res["bytes_freed"] == 4000
    assert not f1.exists()
    assert f2.exists()
    assert f3.exists()


def test_sqlite_wal_checkpoint_management(storage_env):
    """Verify WAL checkpoint manager performs PASSIVE and TRUNCATE checkpoints correctly."""
    repo = storage_env["repo"]
    wal_mgr = storage_env["engine"].wal_manager

    # Generate some WAL writes
    with sqlite3.connect(str(repo.db_path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        for i in range(100):
            conn.execute(
                "INSERT INTO telemetry_logs(timestamp, node_id, audio_class, audio_confidence) VALUES (?, ?, ?, ?)",
                (utc_now(), f"node_wal_{i}", "noise", 0.5),
            )
        conn.commit()

    # Check WAL size
    wal_size = wal_mgr.get_wal_size()
    assert wal_size >= 0

    # Passive checkpoint
    res_passive = wal_mgr.checkpoint(mode="PASSIVE")
    assert res_passive["success"] is True
    assert res_passive["mode"] == "PASSIVE"

    # Truncate checkpoint
    res_trunc = wal_mgr.checkpoint(mode="TRUNCATE")
    assert res_trunc["success"] is True
    assert res_trunc["mode"] == "TRUNCATE"
    # After TRUNCATE, WAL size should be 0 bytes
    assert wal_mgr.get_wal_size() == 0


def test_protected_data_survives_cleanup(storage_env):
    """
    STRICT SAFETY TEST:
    Cleanup must NEVER delete:
    1. Active/unresolved incidents
    2. Evidence linked to open/unresolved incidents
    3. Evidence linked to recent incidents (within retention)
    4. Audit records (operator_actions, incident_notes, schema_migrations)
    5. Unsynced outbox records (PENDING, DEAD_LETTER)
    """
    repo = storage_env["repo"]
    engine = storage_env["engine"]
    evidence_dir = storage_env["evidence_dir"]

    now_dt = datetime.now(timezone.utc)
    old_ts = (now_dt - timedelta(days=60)).isoformat()
    recent_ts = (now_dt - timedelta(days=5)).isoformat()

    # 1. Create incidents
    # - Incident A: OPEN (active, created 60 days ago - must NOT be deleted)
    # - Incident B: CLOSED (recent, created 5 days ago - must NOT be deleted)
    # - Incident C: CLOSED (old, created 60 days ago - evidence can be pruned)
    with sqlite3.connect(str(repo.db_path)) as conn:
        conn.execute(
            """
            INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at)
            VALUES('INC-ACTIVE', 'uuid-1', 'smoke', 'ZONE_B', 'OPEN', ?, ?)
            """,
            (old_ts, old_ts),
        )
        conn.execute(
            """
            INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at)
            VALUES('INC-CLOSED-RECENT', 'uuid-2', 'fire', 'ZONE_B', 'CLOSED', ?, ?)
            """,
            (recent_ts, recent_ts),
        )
        conn.execute(
            """
            INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at)
            VALUES('INC-CLOSED-OLD', 'uuid-3', 'crash', 'ZONE_B', 'CLOSED', ?, ?)
            """,
            (old_ts, old_ts),
        )

        # 2. Create physical evidence files
        ev_active = evidence_dir / "active_keyframe.jpg"
        ev_recent = evidence_dir / "recent_keyframe.jpg"
        ev_old = evidence_dir / "old_keyframe.jpg"
        ev_active.write_bytes(b"ACTIVE_EVIDENCE_DATA")
        ev_recent.write_bytes(b"RECENT_EVIDENCE_DATA")
        ev_old.write_bytes(b"OLD_EVIDENCE_DATA")

        conn.execute(
            "INSERT INTO evidence(incident_id, timestamp, kind, source_path, sha256) VALUES(?,?,?,?,?)",
            ("INC-ACTIVE", old_ts, "keyframe", str(ev_active), "sha_active"),
        )
        conn.execute(
            "INSERT INTO evidence(incident_id, timestamp, kind, source_path, sha256) VALUES(?,?,?,?,?)",
            ("INC-CLOSED-RECENT", recent_ts, "keyframe", str(ev_recent), "sha_recent"),
        )
        conn.execute(
            "INSERT INTO evidence(incident_id, timestamp, kind, source_path, sha256) VALUES(?,?,?,?,?)",
            ("INC-CLOSED-OLD", old_ts, "keyframe", str(ev_old), "sha_old"),
        )

        # 3. Create Audit Records
        conn.execute(
            "INSERT INTO operator_actions(incident_id, timestamp, operator_id, action, approved, payload_json) VALUES(?,?,?,?,?,?)",
            ("INC-ACTIVE", old_ts, "commander_1", "dispatch", 1, "{}"),
        )
        conn.execute(
            "INSERT INTO incident_notes(incident_id, timestamp, operator_id, operator_role, note) VALUES(?,?,?,?,?)",
            ("INC-ACTIVE", old_ts, "operator_1", "OPERATOR", "Critical corridor observation"),
        )

        # 4. Create Sync Outbox records:
        # PENDING (must NOT be deleted)
        # DEAD_LETTER (must NOT be deleted)
        # SYNCED (old, can be pruned)
        conn.execute(
            """
            INSERT INTO sync_outbox(idempotency_key, target, payload_type, payload_json, status, priority, next_attempt_at, created_at, updated_at)
            VALUES('k-pending', 'cloud', 'incident', '{}', 'PENDING', 'HIGH', ?, ?, ?)
            """,
            (old_ts, old_ts, old_ts),
        )
        conn.execute(
            """
            INSERT INTO sync_outbox(idempotency_key, target, payload_type, payload_json, status, priority, next_attempt_at, created_at, updated_at)
            VALUES('k-dead', 'cloud', 'incident', '{}', 'DEAD_LETTER', 'HIGH', ?, ?, ?)
            """,
            (old_ts, old_ts, old_ts),
        )
        conn.execute(
            """
            INSERT INTO sync_outbox(idempotency_key, target, payload_type, payload_json, status, priority, next_attempt_at, created_at, updated_at)
            VALUES('k-synced', 'cloud', 'incident', '{}', 'SYNCED', 'NORMAL', ?, ?, ?)
            """,
            (old_ts, old_ts, old_ts),
        )
        conn.commit()

    # Run full system cleanup with retention = 30 days
    cleanup_res = engine.run_full_cleanup(dry_run=False)
    assert cleanup_res["dry_run"] is False

    # VERIFY PROTECTED ARTIFACTS SURVIVED:

    # 1. Active incident survives intact
    with sqlite3.connect(str(repo.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        inc_active = cur.execute("SELECT * FROM incidents WHERE incident_id='INC-ACTIVE'").fetchone()
        assert inc_active is not None
        assert inc_active["status"] == "OPEN"

        # 2. Evidence linked to ACTIVE incident survives on disk and DB
        assert ev_active.exists()
        ev_row_active = cur.execute("SELECT * FROM evidence WHERE incident_id='INC-ACTIVE'").fetchone()
        assert ev_row_active is not None

        # 3. Evidence linked to RECENT incident survives on disk and DB
        assert ev_recent.exists()
        ev_row_recent = cur.execute("SELECT * FROM evidence WHERE incident_id='INC-CLOSED-RECENT'").fetchone()
        assert ev_row_recent is not None

        # 4. Evidence linked to OLD CLOSED incident was safely pruned
        assert not ev_old.exists()
        ev_row_old = cur.execute("SELECT * FROM evidence WHERE incident_id='INC-CLOSED-OLD'").fetchone()
        assert ev_row_old is None

        # 5. Audit records (operator_actions, incident_notes) 100% SURVIVE
        act_row = cur.execute("SELECT * FROM operator_actions WHERE incident_id='INC-ACTIVE'").fetchone()
        assert act_row is not None
        assert act_row["action"] == "dispatch"

        note_row = cur.execute("SELECT * FROM incident_notes WHERE incident_id='INC-ACTIVE'").fetchone()
        assert note_row is not None
        assert note_row["note"] == "Critical corridor observation"

        # 6. Unsynced outbox records (PENDING, DEAD_LETTER) SURVIVE
        outbox_pending = cur.execute("SELECT * FROM sync_outbox WHERE idempotency_key='k-pending'").fetchone()
        assert outbox_pending is not None
        assert outbox_pending["status"] == "PENDING"

        outbox_dead = cur.execute("SELECT * FROM sync_outbox WHERE idempotency_key='k-dead'").fetchone()
        assert outbox_dead is not None
        assert outbox_dead["status"] == "DEAD_LETTER"

        # Old SYNCED row was pruned
        outbox_synced = cur.execute("SELECT * FROM sync_outbox WHERE idempotency_key='k-synced'").fetchone()
        assert outbox_synced is None


def test_simulated_full_disk_thresholds(storage_env):
    """Verify storage thresholds detect warning and critical levels, surfacing to health monitor."""
    engine = storage_env["engine"]
    status_helper = StorageSafetyStatus(engine=engine)
    health_mon = HealthMonitor(repository=storage_env["repo"], config=storage_env["config"])

    # Simulate healthy disk (> 1 MB free)
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = MagicMock(free=5000000, total=10000000, used=5000000)
        st = status_helper.get_status()
        assert st["status"] == "OK"
        assert st["reason_code"] == "NOMINAL"

        h_poll = health_mon.poll()
        assert h_poll["components"]["storage"]["status"] == "OK"

    # Simulate storage warning (< 1 MB free, > 200 KB free)
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = MagicMock(free=800000, total=10000000, used=9200000)
        st = status_helper.get_status()
        assert st["status"] == "DEGRADED"
        assert st["reason_code"] == "STORAGE_WARNING"

        health_mon.warn_storage = 1000000
        health_mon.crit_storage = 200000
        h_poll = health_mon.poll()
        assert h_poll["components"]["storage"]["status"] == "DEGRADED"

    # Simulate critical storage (< 200 KB free)
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = MagicMock(free=150000, total=10000000, used=9850000)
        st = status_helper.get_status()
        assert st["status"] == "DOWN"
        assert st["reason_code"] == "STORAGE_CRITICAL"

        health_mon.warn_storage = 1000000
        health_mon.crit_storage = 200000
        h_poll = health_mon.poll()
        assert h_poll["components"]["storage"]["status"] == "DOWN"


def test_simulated_multi_day_outage_and_catchup(storage_env):
    """
    Verify outbox behavior across multi-day outage:
    1. Items accumulate while network is down.
    2. Cap policy drops only LOW priority items, strictly protecting HIGH and AUDIT items.
    3. Exponential backoff occurs.
    4. Upon network restoration, batch catch-up successfully drains all accumulated items.
    """
    repo = storage_env["repo"]
    outbox = OfflineSyncOutbox(repository=repo)
    outbox.max_rows = 10  # Low cap for test

    # Simulate network down: enqueue 8 LOW priority telemetry items and 4 HIGH/AUDIT items
    for i in range(8):
        outbox.enqueue(
            idempotency_key=f"telem_{i}",
            target="cloud",
            payload_type="telemetry",
            payload={"metric": i},
            priority="LOW",
        )
    for i in range(4):
        outbox.enqueue(
            idempotency_key=f"audit_{i}",
            target="cloud",
            payload_type="audit",
            payload={"action": f"command_{i}"},
            priority="HIGH",
        )

    # Wait for writer queue flush
    time.sleep(0.2)

    # Check that cap policy pruned LOW items to make room, but ALL HIGH items are preserved
    with sqlite3.connect(str(repo.db_path)) as conn:
        high_count = conn.execute("SELECT count(*) FROM sync_outbox WHERE priority='HIGH'").fetchone()[0]
        assert high_count == 4  # Strictly preserved!

    # Simulate multi-day outage: network calls fail
    failed_sync = lambda target, ptype, payload: False

    # Attempt draining - items back off
    outbox.drain_batch(failed_sync, limit=20)
    time.sleep(0.2)

    with sqlite3.connect(str(repo.db_path)) as conn:
        attempts_sum = conn.execute("SELECT sum(attempts) FROM sync_outbox").fetchone()[0]
        assert attempts_sum > 0

    # Simulate network restoration:
    # 1. Reset backoff timers for immediate catch-up
    outbox.reset_backoff_for_catchup()
    time.sleep(0.1)

    # 2. Successful sync function
    synced_items = []

    def successful_sync(target, ptype, payload):
        synced_items.append((target, ptype, payload))
        return True

    # 3. Catch-up in batches
    total_drained = outbox.catch_up(successful_sync, batch_size=5, max_batches=10)
    time.sleep(0.2)

    assert total_drained > 0
    assert len(synced_items) == total_drained

    # Check status summary
    summary = outbox.status_summary()
    assert summary["PENDING"] == 0
    assert summary["SYNCED"] == total_drained


def test_storage_cleanup_log_persistence(storage_env):
    """Verify every cleanup action is recorded in storage_cleanup_logs."""
    repo = storage_env["repo"]
    engine = storage_env["engine"]

    engine.run_full_cleanup(dry_run=True)

    with sqlite3.connect(str(repo.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM storage_cleanup_logs ORDER BY id DESC").fetchall()
        assert len(rows) > 0
        last = rows[0]
        assert last["policy_type"] == "full_system"
        assert last["dry_run"] == 1
        details = json.loads(last["details_json"])
        assert "subsystems" in details
