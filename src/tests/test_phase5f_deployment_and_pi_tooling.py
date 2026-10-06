"""
Comprehensive Test Suite for Phase 5F: Deployment Packaging and Raspberry Pi Validation Tools.
Covers:
- Production config schema and validation
- Database online backup, restore, integrity checking, and tamper detection
- Startup and crash recovery audits (outbox reconciliation, stale locks)
- Supervisor probes (/healthz, /readyz, /api/system/version) and permission matrix
- Version metadata provider
- Hardware benchmark scripts (CPU/memory, camera FPS, audio latency, sensor contention, thermal, storage)
- Deployment artifacts (systemd service, backup timer, release checklist, deployment guide)
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import sqlite3
import time
import pytest

from src.modules.core.config_validator import (
    validate_config,
    validate_or_raise,
    load_and_validate_config,
    ConfigValidationError,
)
from src.modules.core.version import get_version_info, SCHEMA_VERSION
from src.modules.maintenance.backup import (
    create_online_backup,
    restore_backup,
    verify_database_integrity,
    BackupIntegrityError,
)
from src.modules.maintenance.recovery import run_startup_recovery
from src.modules.security.permission_matrix import check_endpoint_permission

# Pi benchmark modules
from scripts.pi.benchmark_cpu_memory import run_benchmark as bench_cpu_mem
from scripts.pi.benchmark_camera_fps import run_benchmark as bench_cam_fps
from scripts.pi.benchmark_audio_latency import run_benchmark as bench_audio_lat
from scripts.pi.benchmark_sensor_contention import run_benchmark as bench_sensor_cont
from scripts.pi.benchmark_thermal import run_benchmark as bench_thermal
from scripts.pi.benchmark_storage_latency import run_benchmark as bench_storage_lat


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 1. Config Schema and Validation Tests
# ---------------------------------------------------------------------------

def test_production_config_schema_validation():
    prod_path = REPO_ROOT / "src" / "config" / "production.json"
    assert prod_path.is_file(), "production.json must exist"

    cfg = load_and_validate_config(prod_path)
    assert isinstance(cfg, dict)
    assert cfg["system"]["environment"] == "production"
    assert cfg["database"]["db_path"] == "data/emergency_events.db"
    assert cfg["risk"]["thresholds"]["LOW"] < cfg["risk"]["thresholds"]["MEDIUM"] < cfg["risk"]["thresholds"]["HIGH"] < cfg["risk"]["thresholds"]["CRITICAL"]


def test_config_validation_rejections():
    # Valid sample config
    valid_sample = {
        "fusion": {
            "weights": {"audio": 0.3, "vision": 0.3, "sensors": 0.25, "reliability": 0.15},
            "minimum_modalities": 2
        },
        "temporal": {
            "window_size": 6,
            "positive_frames": 3,
            "minimum_average_confidence": 0.6,
            "consecutive_positive": 2,
        },
        "risk": {
            "weights": {"fusion": 0.36, "persistence": 0.2, "reliability": 0.18, "modalities": 0.14, "zone": 0.12},
            "thresholds": {"LOW": 30, "MEDIUM": 50, "HIGH": 70, "CRITICAL": 85}
        },
        "governance": {
            "merge_window_seconds": 120,
            "writer_queue_size": 256,
            "evidence_root": "data/evidence"
        },
        "monitoring": {
            "drift": {"rolling_window_samples": 50, "minimum_samples_guard": 10, "snapshot_interval_seconds": 60},
            "health": {"poll_interval_seconds": 5, "storage_warning_bytes": 1000000, "storage_critical_bytes": 250000},
            "streams": {
                "camera": {"target_fps": 15.0},
                "audio": {"sample_rate": 16000}
            }
        },
        "storage": {
            "retention": {"raw_telemetry_days": 7, "dvr_max_bytes": 5000000, "evidence_retention_days": 30},
            "wal": {"checkpoint_mode": "PASSIVE"}
        }
    }
    assert len(validate_config(valid_sample)) == 0

    # 1. Invalid weight (out of bounds)
    bad_weights = json.loads(json.dumps(valid_sample))
    bad_weights["fusion"]["weights"]["audio"] = 1.5
    errors = validate_config(bad_weights)
    assert any("fusion.weights.audio" in e for e in errors)

    # 2. Inverted thresholds
    bad_thresh = json.loads(json.dumps(valid_sample))
    bad_thresh["risk"]["thresholds"]["LOW"] = 90
    bad_thresh["risk"]["thresholds"]["CRITICAL"] = 20
    errors = validate_config(bad_thresh)
    assert any("risk.thresholds must satisfy" in e for e in errors)

    # 3. Invalid storage WAL checkpoint mode
    bad_wal = json.loads(json.dumps(valid_sample))
    bad_wal["storage"]["wal"]["checkpoint_mode"] = "INVALID_MODE"
    errors = validate_config(bad_wal)
    assert any("checkpoint_mode" in e for e in errors)

    with pytest.raises(ConfigValidationError):
        validate_or_raise(bad_wal)


# ---------------------------------------------------------------------------
# 2. Version Metadata Provider Tests
# ---------------------------------------------------------------------------

def test_version_metadata():
    v = get_version_info()
    assert v["version"] == "0.5.0"
    assert isinstance(v["git_hash"], str) and len(v["git_hash"]) >= 7
    assert v["schema_version"] == 7
    assert "Raspberry Pi 4" in v["target_platform"]
    assert "build_date" in v


# ---------------------------------------------------------------------------
# 3. Online Backup, Restore, and Integrity Verification Tests
# ---------------------------------------------------------------------------

def test_database_backup_and_restore(tmp_path):
    src_db = tmp_path / "source.db"
    backup_db = tmp_path / "backup.db"
    restored_db = tmp_path / "restored.db"

    # Create dummy source database with records
    con = sqlite3.connect(str(src_db))
    with con:
        con.execute("CREATE TABLE test_data (id INTEGER PRIMARY KEY, name TEXT, score REAL)")
        con.execute("INSERT INTO test_data (name, score) VALUES ('alpha', 98.5), ('beta', 85.0), ('gamma', 92.3)")
    con.close()

    # 1. Create online backup
    meta = create_online_backup(src_db, backup_db)
    assert backup_db.is_file()
    assert meta["sha256"]
    assert meta["size_bytes"] > 0
    meta_file = backup_db.with_suffix(".db.meta.json")
    assert meta_file.is_file()

    # 2. Verify integrity of backup
    verify_res = verify_database_integrity(backup_db)
    assert verify_res["status"] == "PASSED"
    assert verify_res["table_counts"].get("test_data") == 3

    # 3. Restore to new location
    restore_res = restore_backup(backup_db, restored_db, verify_checksum=True)
    assert restore_res["status"] == "RESTORED_AND_VERIFIED"
    assert restored_db.is_file()

    # Verify content in restored db
    con_restored = sqlite3.connect(str(restored_db))
    rows = con_restored.execute("SELECT name, score FROM test_data ORDER BY id").fetchall()
    con_restored.close()
    assert len(rows) == 3
    assert rows[0][0] == "alpha"
    assert rows[2][0] == "gamma"

    # 4. Tamper verification test: Corrupt backup and verify restore fails
    with open(backup_db, "r+b") as f:
        f.seek(100)
        f.write(b"CORRUPTED_BYTES_HERE")

    corrupted_restore = tmp_path / "corrupted_restore.db"
    with pytest.raises(BackupIntegrityError):
        restore_backup(backup_db, corrupted_restore, verify_checksum=True)


# ---------------------------------------------------------------------------
# 4. Startup and Crash Recovery Tests
# ---------------------------------------------------------------------------

def test_startup_recovery(tmp_path):
    db_path = tmp_path / "recovery_test.db"
    con = sqlite3.connect(str(db_path))
    with con:
        con.execute("""
            CREATE TABLE sync_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT UNIQUE,
                target TEXT,
                payload_type TEXT,
                status TEXT,
                attempts INTEGER,
                updated_at TEXT
            )
        """)
        con.execute("""
            CREATE TABLE incidents (
                incident_id TEXT PRIMARY KEY,
                incident_uuid TEXT,
                event_type TEXT,
                zone_id TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        con.execute("""
            CREATE TABLE operator_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT,
                timestamp TEXT,
                operator_id TEXT,
                operator_role TEXT,
                action TEXT,
                notes TEXT
            )
        """)
        # Insert stuck in-progress outbox messages
        con.execute("INSERT INTO sync_outbox (idempotency_key, target, payload_type, status, attempts, updated_at) VALUES ('msg-1', 'firebase', 'incident', 'IN_PROGRESS', 1, 'old-ts')")
        con.execute("INSERT INTO sync_outbox (idempotency_key, target, payload_type, status, attempts, updated_at) VALUES ('msg-2', 'firebase', 'incident', 'IN_PROGRESS', 2, 'old-ts')")
        con.execute("INSERT INTO sync_outbox (idempotency_key, target, payload_type, status, attempts, updated_at) VALUES ('msg-3', 'firebase', 'incident', 'PENDING', 0, 'old-ts')")
    con.close()

    # Create dummy stale lock file
    stale_lock = tmp_path / "worker.lock"
    stale_lock.write_text("lock_pid_9999", encoding="utf-8")

    # Run recovery
    rep = run_startup_recovery(db_path)
    assert rep["db_integrity"] == "OK"
    assert rep["stuck_outbox_reconciled"] == 2
    assert rep["stale_locks_removed"] >= 1
    assert not stale_lock.exists()

    # Verify rows in DB were updated
    con = sqlite3.connect(str(db_path))
    in_prog_count = con.execute("SELECT COUNT(*) FROM sync_outbox WHERE status='IN_PROGRESS'").fetchone()[0]
    pending_count = con.execute("SELECT COUNT(*) FROM sync_outbox WHERE status='PENDING'").fetchone()[0]
    actions = con.execute("SELECT action, operator_id FROM operator_actions").fetchall()
    con.close()

    assert in_prog_count == 0
    assert pending_count == 3
    assert any(a[0] == "STARTUP_RECOVERY" for a in actions)


# ---------------------------------------------------------------------------
# 5. Supervisor Probes and Permission Matrix Tests
# ---------------------------------------------------------------------------

def test_supervisor_probes_permissions():
    # Verify /healthz is public
    ok_healthz, status, msg = check_endpoint_permission("/healthz", "GET", None)
    assert ok_healthz is True
    assert status == 200

    # Verify /readyz is public
    ok_readyz, status, msg = check_endpoint_permission("/readyz", "GET", None)
    assert ok_readyz is True
    assert status == 200

    # Verify /api/system/version is public
    ok_ver, status, msg = check_endpoint_permission("/api/system/version", "GET", None)
    assert ok_ver is True
    assert status == 200


# ---------------------------------------------------------------------------
# 6. Raspberry Pi Benchmark Scripts Safe Execution Tests
# ---------------------------------------------------------------------------

def test_pi_benchmark_cpu_memory():
    res = bench_cpu_mem(duration_seconds=1, sample_interval=0.2)
    assert res["benchmark"] == "sustained_cpu_memory"
    assert "cpu_percent_avg" in res["summary"]
    assert "process_rss_mb_avg" in res["summary"]
    assert len(res["samples"]) >= 3


def test_pi_benchmark_camera_fps():
    res = bench_cam_fps(target_frames=10, target_fps=30.0, use_mock=True)
    assert res["benchmark"] == "camera_fps"
    assert res["summary"]["total_frames_captured"] == 10
    assert res["summary"]["measured_fps"] > 0
    assert "frame_jitter_ms" in res["summary"]


def test_pi_benchmark_audio_latency():
    res = bench_audio_lat(duration_seconds=1, hop_sec=0.2, use_mock=True)
    assert res["benchmark"] == "audio_latency"
    assert res["summary"]["windows_processed"] >= 3
    assert res["summary"]["status"] in ("NOMINAL", "DEGRADED")


def test_pi_benchmark_sensor_contention():
    res = bench_sensor_cont(concurrency=2, operations_per_thread=10)
    assert res["benchmark"] == "sensor_bus_contention"
    assert res["summary"]["total_transactions"] == 20
    assert "avg_lock_wait_ms" in res["summary"]


def test_pi_benchmark_thermal():
    res = bench_thermal()
    assert res["benchmark"] == "thermal_throttling"
    assert "status" in res
    assert "throttling" in res


def test_pi_benchmark_storage_latency(tmp_path):
    res = bench_storage_lat(target_dir=str(tmp_path), random_4k_ops=10, seq_64k_ops=5)
    assert res["benchmark"] == "microsd_write_latency"
    assert "avg_fsync_latency_ms" in res["summary"]
    assert res["summary"]["performance_rating"] in ("EXCELLENT", "ACCEPTABLE", "POOR_FLASH_PERFORMANCE")


# ---------------------------------------------------------------------------
# 7. Deployment Artifacts Verification Tests
# ---------------------------------------------------------------------------

def test_deployment_artifacts_exist():
    # systemd files
    service_file = REPO_ROOT / "deploy" / "systemd" / "sentinel.service"
    backup_service = REPO_ROOT / "deploy" / "systemd" / "sentinel-backup.service"
    backup_timer = REPO_ROOT / "deploy" / "systemd" / "sentinel-backup.timer"

    assert service_file.is_file()
    assert backup_service.is_file()
    assert backup_timer.is_file()

    svc_content = service_file.read_text(encoding="utf-8")
    assert "MemoryMax=2.8G" in svc_content
    assert "CPUQuota=350%" in svc_content
    assert "Restart=always" in svc_content
    assert "WatchdogSec=30s" in svc_content

    # Documentation files
    checklist_file = REPO_ROOT / "docs" / "RELEASE_CHECKLIST.md"
    deploy_file = REPO_ROOT / "docs" / "DEPLOYMENT.md"
    assert checklist_file.is_file()
    assert deploy_file.is_file()

    assert len(checklist_file.read_text(encoding="utf-8")) > 500
    assert len(deploy_file.read_text(encoding="utf-8")) > 1000
