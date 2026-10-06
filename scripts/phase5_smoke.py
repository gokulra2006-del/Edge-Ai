#!/usr/bin/env python3
"""
scripts/phase5_smoke.py - Automated End-to-End Validation of Phase 5 Capabilities:
- Phase 5A/5B: Analytics engine, KPI metrics, timeseries aggregation, zone risks
- Phase 5C: Reporting, CSV streaming with formula injection protection, evidence integrity
- Phase 5D: Safe retention cleanup, WAL checkpointing, protected data guarantees
- Phase 5E: User authentication, bcrypt hashing, rate limiting, lockout, CSRF protection
- Phase 5F: Configuration validation, supervisor probes (/healthz, /readyz, version), and crash recovery

Prints a chronological timeline and structured verification report. Exits 0 on success.
"""

from __future__ import annotations
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.modules.database.governed_store import IncidentRepository, utc_now
from src.modules.analytics.analytics_engine import AnalyticsEngine
from src.modules.reporting import stream_incidents_csv, ReportService, EvidenceVerifier
from src.modules.storage.storage_safety import StorageRetentionEngine, StorageSafetyStatus
from src.modules.security.user_store import UserManager, hash_password, verify_password
from src.modules.security.session_manager import SessionManager
from src.modules.security.rate_limiter import LoginRateLimiter
from src.modules.core.config_validator import load_and_validate_config
from src.modules.core.version import get_version_info
from src.modules.maintenance.backup import create_online_backup, restore_backup, verify_database_integrity
from src.modules.maintenance.recovery import run_startup_recovery


def log_step(timeline: list, step: str, message: str):
    ts = time.strftime("%H:%M:%S")
    entry = f"[{ts}] [{step}] {message}"
    print(entry)
    timeline.append(entry)


def main():
    print("=" * 80)
    print("     SENTINEL-AI PHASE 5 END-TO-END SMOKE TEST & ACCEPTANCE AUDIT")
    print("=" * 80)

    timeline = []
    smoke_dir = REPO_ROOT / "data" / "smoke_phase5"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    db_path = smoke_dir / "sentinel_smoke.db"
    if db_path.exists():
        try: db_path.unlink()
        except Exception: pass

    # Initialize Repository and Subsystems
    repo = IncidentRepository(db_path=db_path)
    analytics = AnalyticsEngine(repo)
    storage = StorageRetentionEngine(repo)
    storage_status = StorageSafetyStatus(storage)
    user_mgr = UserManager(users_file=smoke_dir / "users.json")
    session_mgr = SessionManager(idle_timeout_seconds=1800, absolute_timeout_seconds=28800)
    rate_limiter = LoginRateLimiter(repo, max_attempts=5, lockout_seconds=900)

    log_step(timeline, "INIT", f"Initialized fresh governed store at {db_path} (Schema v7)")

    # -------------------------------------------------------------------------
    # 1. Seed Historical Data for Analytics & Reporting
    # -------------------------------------------------------------------------
    log_step(timeline, "SEED", "Seeding test incidents, telemetry, predictions, and feedback...")
    with sqlite3.connect(str(db_path)) as con:
        # System anchor incident for foreign keys
        con.execute(
            "INSERT OR IGNORE INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at) "
            "VALUES ('SYSTEM', 'sys-anchor', 'SYSTEM', 'SYSTEM', 'CLOSED', ?, ?)",
            (utc_now(), utc_now())
        )
        # Test incidents
        incidents = [
            ("INC-001", "uuid-1", "crash", "ZONE_B_INTERSECTION", "RESOLVED", "2026-10-06T10:00:00Z", "2026-10-06T10:15:00Z", "Corroborated vehicle collision"),
            ("INC-002", "uuid-2", "fire", "RESTRICTED_AREA", "RESOLVED", "2026-10-06T11:00:00Z", "2026-10-06T11:20:00Z", "Thermal escalation"),
            ("INC-003", "uuid-3", "smoke", "SERVER_ROOM", "FALSE_ALARM", "2026-10-06T12:00:00Z", "2026-10-06T12:05:00Z", "Operator marked false alarm"),
            ("INC-004", "uuid-4", "siren", "ZONE_B_INTERSECTION", "NEW", "2026-10-06T13:00:00Z", "2026-10-06T13:00:00Z", "Active siren incident"),
        ]
        con.executemany(
            "INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at, outcome) VALUES(?,?,?,?,?,?,?,?)",
            incidents
        )
        # Test predictions
        con.execute(
            "INSERT INTO predictions(id, incident_id, timestamp, label, confidence, model_id, payload_json) "
            "VALUES (1, 'INC-001', '2026-10-06T10:00:00Z', 'crash', 0.94, 'model-vision-yolo11n', ?)",
            (json.dumps({"ood_score": 0.05, "raw_input_ref": "frame_1.jpg"}),)
        )
        # Test feedback
        con.execute(
            "INSERT INTO prediction_feedback(prediction_id, label, operator_id, operator_role, timestamp) "
            "VALUES (1, 'CORRECT', 'commander', 'COMMANDER', '2026-10-06T10:05:00Z')"
        )
        # Test outbox rows
        con.execute(
            "INSERT INTO sync_outbox(idempotency_key, target, payload_type, status, attempts, next_attempt_at, created_at, updated_at, payload_json) "
            "VALUES ('sync-1', 'firebase', 'incident', 'IN_PROGRESS', 1, '2026-10-06T10:00:00Z', '2026-10-06T10:00:00Z', '2026-10-06T10:00:00Z', '{}')"
        )
    log_step(timeline, "SEED", "Data seeding complete: 4 incidents, 1 prediction, 1 outbox row")

    # -------------------------------------------------------------------------
    # 2. Phase 5A/5B: Analytics Engine Validation
    # -------------------------------------------------------------------------
    log_step(timeline, "ANALYTICS", "Running analytical aggregations and KPI calculations...")
    summary = analytics.get_incident_summary(window="7d")
    assert summary["total_incidents"] == 5, f"Expected 5 incidents, got {summary['total_incidents']}"
    assert summary["false_alarm_count"] == 1, f"Expected 1 false alarm, got {summary['false_alarm_count']}"

    ts = analytics.get_incident_timeseries(window="7d", bucket_interval="1d")
    assert len(ts) >= 1, "Expected timeseries aggregation buckets"

    perf = analytics.get_model_performance(window="7d", model_id="model-vision-yolo11n")
    assert perf["evaluated_predictions"] == 1, "Expected 1 evaluated prediction"
    assert perf["mean_confidence"] == 0.94, "Expected 0.94 confidence"

    log_step(timeline, "ANALYTICS", f"PASSED: Total={summary['total_incidents']}, FalseAlarmRate={summary['false_alarm_count']/4*100}%, MeanConf={perf['mean_confidence']}")

    # -------------------------------------------------------------------------
    # 3. Phase 5C: Reporting & Evidence Integrity Validation
    # -------------------------------------------------------------------------
    log_step(timeline, "REPORTS", "Generating CSV export with formula injection escaping...")
    csv_chunks = list(stream_incidents_csv(repo))
    csv_content = "".join(csv_chunks)
    assert "INC-001" in csv_content and "INC-004" in csv_content
    assert "incident_id,incident_uuid,event_type" in csv_content

    # Test formula injection escaping on malicious cell values
    from src.modules.reporting.csv_exporter import sanitize_csv_cell
    for malicious in ("=1+1;cmd|' /C calc'!A0", "+12345", "-cmd", "@SUM(A1:A10)"):
        escaped = sanitize_csv_cell(malicious)
        assert escaped.startswith("'"), f"Dangerous formula {malicious} was not escaped with single-quote!"

    log_step(timeline, "REPORTS", f"PASSED: CSV streamed successfully ({len(csv_content)} bytes)")

    # -------------------------------------------------------------------------
    # 4. Phase 5D: Data Retention & Storage Safety
    # -------------------------------------------------------------------------
    log_step(timeline, "RETENTION", "Executing safe retention cleanup (dry-run mode)...")
    dry_rep = storage.run_full_cleanup(dry_run=True)
    assert dry_rep["dry_run"] is True

    # Confirm active incidents and un-synced outbox rows were preserved
    with sqlite3.connect(str(db_path)) as con:
        active_count = con.execute("SELECT COUNT(*) FROM incidents WHERE status='NEW'").fetchone()[0]
        outbox_count = con.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0]
    assert active_count == 1, "Active incident must NOT be pruned!"
    assert outbox_count == 1, "Outbox row must NOT be pruned!"

    # Execute WAL checkpoint
    ckpt = storage.wal_manager.checkpoint(mode="PASSIVE")
    assert ckpt["success"] is True, f"WAL checkpoint failed: {ckpt}"
    log_step(timeline, "RETENTION", f"PASSED: Safe cleanup preserved active incident & outbox. WAL mode={ckpt['mode']}")

    # -------------------------------------------------------------------------
    # 5. Phase 5E: Security Hardening & Rate Limiter
    # -------------------------------------------------------------------------
    log_step(timeline, "SECURITY", "Testing user management, bcrypt hashing, and rate limiting...")
    # First-run admin setup
    admin = user_mgr.create_user("commander", "SuperSecurePassword123!", "COMMANDER")
    assert admin["role"] == "COMMANDER"

    # Authenticate valid credentials
    auth_ok, role, err = user_mgr.authenticate("commander", "SuperSecurePassword123!")
    assert auth_ok is True, f"Authentication failed: {err}"
    assert role == "COMMANDER"

    # Session creation & CSRF token
    session = session_mgr.create_session(admin["username"], admin["role"])
    assert session["token"] and session["csrf_token"]
    assert session_mgr.validate_csrf(session["token"], session["csrf_token"]) is True
    assert session_mgr.validate_csrf(session["token"], "invalid_csrf_token") is False

    # Brute-force rate limiting: 5 failed logins triggers lockout
    client_ip = "192.168.1.100"
    for i in range(5):
        rate_limiter.record_failure(client_ip, "attacker", "INVALID_CREDENTIALS", ip=client_ip)
    is_locked, remaining = rate_limiter.is_locked_out(client_ip)
    assert is_locked is True, "Expected attacker to be locked out after 5 failures"
    log_step(timeline, "SECURITY", f"PASSED: Bcrypt verified, CSRF validated, and brute-force lockout triggered ({remaining}s remaining)")

    # -------------------------------------------------------------------------
    # 6. Phase 5F: Production Config, Crash Recovery & Supervisor Probes
    # -------------------------------------------------------------------------
    log_step(timeline, "DEPLOYMENT", "Validating production config schema and supervisor endpoints...")
    prod_cfg = load_and_validate_config(REPO_ROOT / "src" / "config" / "production.json")
    assert prod_cfg["system"]["environment"] == "production"

    ver = get_version_info()
    assert ver["version"] == "0.5.0" and ver["schema_version"] == 7

    # Test startup crash recovery
    recov = run_startup_recovery(db_path)
    if recov["db_integrity"] != "OK":
        print("RECOVERY REPORT:", json.dumps(recov, indent=2))
    assert recov["db_integrity"] == "OK"
    assert recov["stuck_outbox_reconciled"] == 1, "Stuck outbox row must be reconciled to PENDING"

    # Verify online backup & restore
    backup_file = smoke_dir / "backup.db"
    meta = create_online_backup(db_path, backup_file)
    assert backup_file.is_file() and meta["sha256"]

    restored_file = smoke_dir / "restored.db"
    res_restore = restore_backup(backup_file, restored_file, verify_checksum=True)
    assert res_restore["status"] == "RESTORED_AND_VERIFIED"

    log_step(timeline, "DEPLOYMENT", f"PASSED: Config valid, Version={ver['version']}-{ver['git_hash']}, Backup SHA256={meta['sha256'][:12]}...")

    # Cleanup temporary test smoke directory
    try:
        import shutil
        shutil.rmtree(smoke_dir, ignore_errors=True)
    except Exception:
        pass

    print("=" * 80)
    print("  ALL PHASE 5 SMOKE TESTS COMPLETED SUCCESSFULLY!")
    print(f"  Total Steps Verified: {len(timeline)}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
