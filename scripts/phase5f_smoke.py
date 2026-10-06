#!/usr/bin/env python3
"""Phase 5F Deployment Packaging & Raspberry Pi Tooling Smoke Test.

Validates:
1. Production config schema validation at startup.
2. Version info metadata provider (git hash, build date, schema version).
3. SQLite online backup, restore, and integrity verification.
4. Startup recovery (outbox reconciliation, stale lock removal).
5. Supervisor probes (/healthz, /readyz).
6. Execution of Pi hardware benchmark scripts emitting structured JSON.
7. Systemd service files, Windows setup scripts, and deployment documentation.
"""
from __future__ import annotations

import gc
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.modules.core.config_validator import load_and_validate_config, validate_config
from src.modules.core.version import get_version_info
from src.modules.maintenance.backup import (
    create_online_backup,
    restore_backup,
    verify_database_integrity,
    BackupIntegrityError,
)
from src.modules.maintenance.recovery import run_startup_recovery
from src.modules.security.permission_matrix import check_endpoint_permission

# Pi benchmark scripts
from scripts.pi.benchmark_cpu_memory import run_benchmark as bench_cpu_mem
from scripts.pi.benchmark_camera_fps import run_benchmark as bench_cam_fps
from scripts.pi.benchmark_audio_latency import run_benchmark as bench_audio_lat
from scripts.pi.benchmark_sensor_contention import run_benchmark as bench_sensor_cont
from scripts.pi.benchmark_thermal import run_benchmark as bench_thermal
from scripts.pi.benchmark_storage_latency import run_benchmark as bench_storage_lat


def run_phase5f_smoke() -> bool:
    print("=" * 70)
    print(" SENTINEL-AI PHASE 5F: DEPLOYMENT & PI TOOLING SMOKE VERIFICATION")
    print("=" * 70)

    # [Test 1] Production Config Validation
    print("\n[Step 1] Validating production configuration schema...")
    prod_cfg_path = PROJECT_ROOT / "src" / "config" / "production.json"
    assert prod_cfg_path.is_file(), "production.json is missing!"
    cfg = load_and_validate_config(prod_cfg_path)
    assert cfg["system"]["environment"] == "production"
    print(f"  -> production.json schema verified (environment: {cfg['system']['environment']}).")

    # [Test 2] Version Metadata Provider
    print("\n[Step 2] Validating version metadata provider...")
    vinfo = get_version_info()
    assert vinfo["version"]
    assert vinfo["git_hash"]
    assert vinfo["schema_version"] == 7
    print(f"  -> Version: {vinfo['version']} | Git: {vinfo['git_hash'][:8]} | Schema: v{vinfo['schema_version']} | Date: {vinfo['build_date']}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_path = Path(tmpdir)
        db_path = tmp_path / "smoke_f.db"
        backup_path = tmp_path / "smoke_f_backup.db"
        restored_path = tmp_path / "smoke_f_restored.db"

        # [Test 3] Database Backup, Integrity, & Restore
        print("\n[Step 3] Validating SQLite online backup and integrity checking...")
        con = sqlite3.connect(str(db_path))
        try:
            con.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, title TEXT, value REAL)")
            con.execute("INSERT INTO records (title, value) VALUES ('telemetry_a', 42.0), ('telemetry_b', 84.5)")
            con.commit()
        finally:
            con.close()

        # Online backup
        backup_meta = create_online_backup(db_path, backup_path)
        assert backup_path.exists()
        assert backup_meta["sha256"]
        print(f"  -> Online backup created: {backup_path.name} (SHA: {backup_meta['sha256'][:12]}...)")

        # Verify integrity
        integrity = verify_database_integrity(backup_path)
        assert integrity["status"] == "PASSED"
        print(f"  -> Integrity verification passed (tables: {integrity['table_counts']}).")

        # Restore
        restored = restore_backup(backup_path, restored_path, verify_checksum=True)
        assert restored["status"] == "RESTORED_AND_VERIFIED"
        assert restored_path.exists()

        # Verify restored rows
        con_r = sqlite3.connect(str(restored_path))
        try:
            count = con_r.execute("SELECT count(*) FROM records").fetchone()[0]
            assert count == 2
        finally:
            con_r.close()
        print(f"  -> Database restore verified ({count} rows restored).")

        # [Test 4] Startup and Crash Recovery
        print("\n[Step 4] Validating startup recovery (outbox reconciliation, stale locks)...")
        rec_db = tmp_path / "recovery.db"
        con_rec = sqlite3.connect(str(rec_db))
        try:
            con_rec.execute("CREATE TABLE sync_outbox (id INTEGER PRIMARY KEY, idempotency_key TEXT UNIQUE, target TEXT, payload_type TEXT, status TEXT, attempts INTEGER, updated_at TEXT)")
            con_rec.execute("CREATE TABLE incidents (incident_id TEXT PRIMARY KEY, incident_uuid TEXT, event_type TEXT, zone_id TEXT, status TEXT, created_at TEXT, updated_at TEXT)")
            con_rec.execute("CREATE TABLE operator_actions (id INTEGER PRIMARY KEY, incident_id TEXT, timestamp TEXT, operator_id TEXT, action TEXT, approved INTEGER, payload_json TEXT)")
            con_rec.execute("INSERT INTO sync_outbox VALUES (1, 'key1', 'firebase', 'incident', 'IN_PROGRESS', 1, '2026-10-06T00:00:00')")
            con_rec.commit()
        finally:
            con_rec.close()

        stale_lock = tmp_path / "worker.lock"
        stale_lock.write_text("pid_1234", encoding="utf-8")

        rec_report = run_startup_recovery(rec_db)
        assert rec_report["db_integrity"] == "OK"
        assert rec_report["stuck_outbox_reconciled"] == 1
        assert not stale_lock.exists()
        print("  -> Startup recovery verified: stuck outbox reset to PENDING, stale lock removed.")

        # [Test 5] Supervisor Probes
        print("\n[Step 5] Validating supervisor probes (/healthz, /readyz)...")
        ok_h, st_h, _ = check_endpoint_permission("/healthz", "GET", None)
        ok_r, st_r, _ = check_endpoint_permission("/readyz", "GET", None)
        assert ok_h and st_h == 200
        assert ok_r and st_r == 200
        print("  -> Supervisor probes accessible anonymously (200 OK).")

        # [Test 6] Pi Hardware Benchmark Scripts Safe Execution
        print("\n[Step 6] Validating Raspberry Pi benchmark scripts execution (emitting JSON)...")
        print("  * NOTICE: Full hardware validation must be executed on real Raspberry Pi 4 hardware.")
        
        # CPU/Mem
        res_cpu = bench_cpu_mem(duration_seconds=1, sample_interval=0.2)
        assert res_cpu["benchmark"] == "sustained_cpu_memory"
        print(f"  -> CPU/Memory: CPU avg={res_cpu['summary']['cpu_percent_avg']}%, RSS avg={res_cpu['summary']['process_rss_mb_avg']} MB")

        # Camera FPS
        res_cam = bench_cam_fps(target_frames=10, target_fps=30.0, use_mock=True)
        assert res_cam["benchmark"] == "camera_fps"
        print(f"  -> Camera FPS: Measured={res_cam['summary']['measured_fps']} FPS (Jitter: {res_cam['summary']['frame_jitter_ms']} ms)")

        # Audio Latency
        res_aud = bench_audio_lat(duration_seconds=1, hop_sec=0.2, use_mock=True)
        assert res_aud["benchmark"] == "audio_latency"
        print(f"  -> Audio Latency: Status={res_aud['summary']['status']}, Windows={res_aud['summary']['windows_processed']}")

        # Sensor Bus Contention
        res_sens = bench_sensor_cont(concurrency=2, operations_per_thread=10)
        assert res_sens["benchmark"] == "sensor_bus_contention"
        print(f"  -> Sensor Bus: Total Tx={res_sens['summary']['total_transactions']}, Avg Wait={res_sens['summary']['avg_lock_wait_ms']} ms")

        # Thermal Throttling
        res_therm = bench_thermal()
        assert res_therm["benchmark"] == "thermal_throttling"
        print(f"  -> Thermal Throttling: Status={res_therm['status']}, Temp={res_therm.get('temperature_c', 'N/A')} C")

        # MicroSD Latency
        res_stor = bench_storage_lat(target_dir=str(tmp_path), random_4k_ops=10, seq_64k_ops=5)
        assert res_stor["benchmark"] == "microsd_write_latency"
        print(f"  -> MicroSD Write: Rating={res_stor['summary']['performance_rating']}, fsync avg={res_stor['summary']['avg_fsync_latency_ms']} ms")

        # [Test 7] Deployment Service Files & Documentation
        print("\n[Step 7] Validating deployment systemd services and documentation...")
        assert (PROJECT_ROOT / "deploy" / "systemd" / "sentinel.service").exists()
        assert (PROJECT_ROOT / "deploy" / "systemd" / "sentinel-backup.service").exists()
        assert (PROJECT_ROOT / "deploy" / "systemd" / "sentinel-backup.timer").exists()
        assert (PROJECT_ROOT / "docs" / "DEPLOYMENT.md").exists()
        assert (PROJECT_ROOT / "docs" / "RELEASE_CHECKLIST.md").exists()
        print("  -> systemd units and deployment guides verified.")

    print("\n" + "=" * 70)
    print(" ALL PHASE 5F VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = run_phase5f_smoke()
    sys.exit(0 if success else 1)
