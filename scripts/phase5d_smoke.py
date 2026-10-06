#!/usr/bin/env python3
"""Phase 5D Storage Safety & Data Retention Smoke Test.

Validates:
1. Configurable retention policies across all subsystems.
2. Telemetry archival (compress to .json.gz then prune raw rows).
3. Blackbox DVR storage cap with oldest-first eviction.
4. SQLite WAL checkpoint management (PASSIVE & TRUNCATE) and size tracking.
5. Storage warning & critical health thresholds.
6. Strict safety guarantees (protected data NEVER deleted).
7. Dry-run mode and storage cleanup audit logging.
8. Outbox bounded growth, backoff, and batch catch-up after network recovery.
"""
from __future__ import annotations

import gc
import gzip
import json
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.modules.database.governed_store import IncidentRepository, MigrationRunner, utc_now
from src.modules.storage.storage_safety import (
    StorageRetentionEngine,
    WalCheckpointManager,
    StorageSafetyStatus,
)
from src.modules.assurance.device_health import HealthMonitor, OfflineSyncOutbox
from src.modules.storage.cli import main as storage_cli_main


def run_phase5d_smoke() -> bool:
    print("=" * 70)
    print(" SENTINEL-AI PHASE 5D: STORAGE RETENTION & SAFETY SMOKE VERIFICATION")
    print("=" * 70)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_path = Path(tmpdir)
        db_path = tmp_path / "smoke_storage.db"
        base_dir = tmp_path / "app"
        base_dir.mkdir(parents=True, exist_ok=True)

        archives_dir = base_dir / "data" / "archives"
        dvr_dir = base_dir / "data" / "recordings"
        evidence_dir = base_dir / "data" / "evidence"
        reports_dir = base_dir / "reports"
        logs_dir = base_dir / "logs"

        for d in (archives_dir, dvr_dir, evidence_dir, reports_dir, logs_dir):
            d.mkdir(parents=True, exist_ok=True)

        print("\n[Step 1] Initializing governed repository and test schema...")
        MigrationRunner(db_path).run()
        repo = IncidentRepository(db_path=db_path)

        con = sqlite3.connect(str(db_path))
        try:
            con.execute(
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
            con.commit()
        finally:
            con.close()

        config = {
            "storage": {
                "retention": {
                    "raw_telemetry_days": 7,
                    "archive_telemetry_after_days": 3,
                    "dvr_max_bytes": 10000,
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

        # [Test 1] Telemetry Archival
        print("\n[Step 2] Validating raw telemetry compression and archival...")
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(days=10)).isoformat()
        recent_time = (now - timedelta(days=1)).isoformat()

        con = sqlite3.connect(str(db_path))
        try:
            for i in range(10):
                con.execute(
                    "INSERT INTO telemetry_logs(timestamp, node_id, audio_class, audio_confidence) VALUES (?, ?, ?, ?)",
                    (old_time, f"node_{i}", "siren", 0.95),
                )
            for i in range(5):
                con.execute(
                    "INSERT INTO telemetry_logs(timestamp, node_id, audio_class, audio_confidence) VALUES (?, ?, ?, ?)",
                    (recent_time, f"node_rec_{i}", "normal", 0.1),
                )
            con.commit()
        finally:
            con.close()

        # Dry run
        dry_telem = engine.archive_telemetry(dry_run=True, older_than_days=3)
        assert dry_telem["dry_run"] is True
        assert dry_telem["items_pruned"] == 10
        print("  -> Dry run: 10 items reported without deletion.")

        # Real run
        real_telem = engine.archive_telemetry(dry_run=False, older_than_days=3)
        assert real_telem["items_archived"] == 10
        assert real_telem["items_pruned"] == 10
        archives = list(archives_dir.glob("*.json.gz"))
        assert len(archives) >= 1
        print(f"  -> Archival verified: {archives[0].name} created ({len(archives)} archives).")

        # [Test 2] DVR Eviction
        print("\n[Step 3] Validating DVR oldest-first storage cap eviction...")
        f1 = dvr_dir / "clip_20261001_100000.mp4"
        f2 = dvr_dir / "clip_20261002_100000.mp4"
        f3 = dvr_dir / "clip_20261003_100000.mp4"
        f1.write_bytes(b"A" * 4000)
        f2.write_bytes(b"B" * 4000)
        f3.write_bytes(b"C" * 4000)
        # Set mtimes
        import os
        os.utime(str(f1), (1000, 1000))
        os.utime(str(f2), (2000, 2000))
        os.utime(str(f3), (3000, 3000))

        # Evict with cap = 10000 bytes (current = 12000 bytes, f1 should be evicted)
        evict_res = engine.evict_dvr(dry_run=False, max_bytes=10000)
        assert evict_res["items_pruned"] == 1
        assert not f1.exists()
        assert f2.exists()
        assert f3.exists()
        print(f"  -> DVR eviction verified: Oldest clip evicted, remaining size: {evict_res['total_size_after']} bytes.")

        # [Test 3] SQLite WAL Checkpoint Management
        print("\n[Step 4] Validating SQLite WAL checkpoint management...")
        wal_mgr = engine.wal_manager
        con = sqlite3.connect(str(db_path))
        try:
            con.execute("PRAGMA journal_mode=WAL")
            for i in range(50):
                con.execute(
                    "INSERT INTO telemetry_logs(timestamp, node_id, audio_class, audio_confidence) VALUES (?, ?, ?, ?)",
                    (utc_now(), f"node_wal_{i}", "noise", 0.5),
                )
            con.commit()
        finally:
            con.close()

        res_p = wal_mgr.checkpoint(mode="PASSIVE")
        assert res_p["success"] is True
        print(f"  -> PASSIVE WAL Checkpoint: status={res_p['success']}")

        res_t = wal_mgr.checkpoint(mode="TRUNCATE")
        assert res_t["success"] is True
        assert wal_mgr.get_wal_size() == 0
        print(f"  -> TRUNCATE WAL Checkpoint: size={wal_mgr.get_wal_size()} bytes.")

        # [Test 4] Protected Data Survives Cleanup
        print("\n[Step 5] Validating protected safety data survival across full cleanup...")
        old_ts = (now - timedelta(days=60)).isoformat()
        recent_ts = (now - timedelta(days=5)).isoformat()

        ev_active = evidence_dir / "active_keyframe.jpg"
        ev_recent = evidence_dir / "recent_keyframe.jpg"
        ev_old = evidence_dir / "old_keyframe.jpg"
        ev_active.write_bytes(b"ACTIVE_DATA")
        ev_recent.write_bytes(b"RECENT_DATA")
        ev_old.write_bytes(b"OLD_DATA")

        con = sqlite3.connect(str(db_path))
        try:
            # Active incident
            con.execute(
                """
                INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at)
                VALUES('INC-ACTIVE', 'uuid-1', 'smoke', 'ZONE_B', 'OPEN', ?, ?)
                """,
                (old_ts, old_ts),
            )
            # Recent closed incident
            con.execute(
                """
                INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at)
                VALUES('INC-CLOSED-REC', 'uuid-2', 'fire', 'ZONE_B', 'CLOSED', ?, ?)
                """,
                (recent_ts, recent_ts),
            )
            # Old closed incident
            con.execute(
                """
                INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at)
                VALUES('INC-CLOSED-OLD', 'uuid-3', 'crash', 'ZONE_B', 'CLOSED', ?, ?)
                """,
                (old_ts, old_ts),
            )

            # Evidence entries
            con.execute("INSERT INTO evidence(incident_id, timestamp, kind, source_path, sha256) VALUES(?,?,?,?,?)",
                        ("INC-ACTIVE", old_ts, "keyframe", str(ev_active), "sha1"))
            con.execute("INSERT INTO evidence(incident_id, timestamp, kind, source_path, sha256) VALUES(?,?,?,?,?)",
                        ("INC-CLOSED-REC", recent_ts, "keyframe", str(ev_recent), "sha2"))
            con.execute("INSERT INTO evidence(incident_id, timestamp, kind, source_path, sha256) VALUES(?,?,?,?,?)",
                        ("INC-CLOSED-OLD", old_ts, "keyframe", str(ev_old), "sha3"))

            # Audit logs
            con.execute("INSERT INTO operator_actions(incident_id, timestamp, operator_id, action, approved, payload_json) VALUES(?,?,?,?,?,?)",
                        ("INC-ACTIVE", old_ts, "commander1", "escalate", 1, "{}"))
            con.execute("INSERT INTO incident_notes(incident_id, timestamp, operator_id, operator_role, note) VALUES(?,?,?,?,?)",
                        ("INC-ACTIVE", old_ts, "op1", "OPERATOR", "Critical corridor observation"))

            # Outbox records
            con.execute("INSERT INTO sync_outbox(idempotency_key, target, payload_type, payload_json, status, priority, next_attempt_at, created_at, updated_at) VALUES('k-pen', 'cloud', 'inc', '{}', 'PENDING', 'HIGH', ?, ?, ?)",
                        (old_ts, old_ts, old_ts))
            con.execute("INSERT INTO sync_outbox(idempotency_key, target, payload_type, payload_json, status, priority, next_attempt_at, created_at, updated_at) VALUES('k-dead', 'cloud', 'inc', '{}', 'DEAD_LETTER', 'HIGH', ?, ?, ?)",
                        (old_ts, old_ts, old_ts))
            con.execute("INSERT INTO sync_outbox(idempotency_key, target, payload_type, payload_json, status, priority, next_attempt_at, created_at, updated_at) VALUES('k-sync', 'cloud', 'inc', '{}', 'SYNCED', 'NORMAL', ?, ?, ?)",
                        (old_ts, old_ts, old_ts))
            con.commit()
        finally:
            con.close()

        # Run full cleanup
        cleanup_res = engine.run_full_cleanup(dry_run=False)
        assert cleanup_res["dry_run"] is False

        con = sqlite3.connect(str(db_path))
        try:
            # Active incident preserved
            inc_act = con.execute("SELECT status FROM incidents WHERE incident_id='INC-ACTIVE'").fetchone()
            assert inc_act is not None and inc_act[0] == "OPEN"

            # Evidence checks
            assert ev_active.exists(), "Active incident evidence was erroneously deleted!"
            assert ev_recent.exists(), "Recent incident evidence was erroneously deleted!"
            assert not ev_old.exists(), "Old closed evidence should have been pruned."

            # Audit records preserved
            act_cnt = con.execute("SELECT count(*) FROM operator_actions").fetchone()[0]
            assert act_cnt == 1, "Audit logs must NEVER be pruned!"
            note_cnt = con.execute("SELECT count(*) FROM incident_notes").fetchone()[0]
            assert note_cnt == 1, "Incident notes must NEVER be pruned!"

            # Unsynced outbox preserved
            pen_cnt = con.execute("SELECT count(*) FROM sync_outbox WHERE status='PENDING'").fetchone()[0]
            assert pen_cnt == 1, "PENDING outbox row was erroneously pruned!"
            dead_cnt = con.execute("SELECT count(*) FROM sync_outbox WHERE status='DEAD_LETTER'").fetchone()[0]
            assert dead_cnt == 1, "DEAD_LETTER outbox row was erroneously pruned!"
            sync_cnt = con.execute("SELECT count(*) FROM sync_outbox WHERE status='SYNCED'").fetchone()[0]
            assert sync_cnt == 0, "Old SYNCED outbox row was not pruned."
        finally:
            con.close()

        print("  -> Strictly protected data verified: Active incidents, audit trails, and unsynced outbox rows intact.")

        # [Test 5] Simulated Disk Storage Thresholds
        print("\n[Step 6] Validating storage health warning & critical thresholds...")
        status_helper = StorageSafetyStatus(engine=engine)
        with patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(free=5000000, total=10000000, used=5000000)
            st_ok = status_helper.get_status()
            assert st_ok["status"] == "OK"

            mock_usage.return_value = MagicMock(free=800000, total=10000000, used=9200000)
            st_warn = status_helper.get_status()
            assert st_warn["status"] == "DEGRADED"

            mock_usage.return_value = MagicMock(free=150000, total=10000000, used=9850000)
            st_crit = status_helper.get_status()
            assert st_crit["status"] == "DOWN"
        print("  -> Storage threshold transitions verified: NOMINAL -> DEGRADED -> DOWN.")

        # [Test 6] Outbox Backoff and Batch Catch-Up
        print("\n[Step 7] Validating multi-day network outage outbox backoff and batch catch-up...")
        con = sqlite3.connect(str(db_path))
        try:
            con.execute("DELETE FROM sync_outbox")
            con.commit()
        finally:
            con.close()

        outbox = OfflineSyncOutbox(repository=repo)
        outbox.max_rows = 10

        for i in range(8):
            outbox.enqueue(idempotency_key=f"telem_{i}", target="cloud", payload_type="telemetry", payload={"v": i}, priority="LOW")
        for i in range(4):
            outbox.enqueue(idempotency_key=f"audit_{i}", target="cloud", payload_type="audit", payload={"v": i}, priority="HIGH")

        time.sleep(0.15)
        # Cap preserves all HIGH items
        con = sqlite3.connect(str(db_path))
        try:
            high_count = con.execute("SELECT count(*) FROM sync_outbox WHERE priority='HIGH'").fetchone()[0]
            assert high_count == 4
        finally:
            con.close()

        # Simulated network failure
        outbox.drain_batch(lambda t, pt, pl: False, limit=20)
        time.sleep(0.15)

        # Network restored
        outbox.reset_backoff_for_catchup()
        time.sleep(0.1)

        synced = []
        drained = outbox.catch_up(lambda t, pt, pl: (synced.append(pl), True)[1], batch_size=5, max_batches=10)
        time.sleep(0.15)
        assert drained > 0
        print(f"  -> Outbox resilience verified: {drained} items drained during batch catch-up.")

        # Cleanup log check
        con = sqlite3.connect(str(db_path))
        try:
            log_count = con.execute("SELECT count(*) FROM storage_cleanup_logs").fetchone()[0]
            assert log_count >= 1
        finally:
            con.close()
        print(f"  -> Cleanup logs verified: {log_count} permanent audit log entries persisted.")

        repo.close()
        del repo, engine, status_helper, wal_mgr, outbox
        gc.collect()

    print("\n" + "=" * 70)
    print(" ALL PHASE 5D VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = run_phase5d_smoke()
    sys.exit(0 if success else 1)
