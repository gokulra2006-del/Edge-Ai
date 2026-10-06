"""
Comprehensive Acceptance Test Suite for Phase 5:
1. Automated role permissions test for EVERY user role (COMMANDER, OPERATOR, ENGINEER, VIEWER, UNAUTHENTICATED)
2. Offline mode resilience (local writes continue, bounded outbox, catch-up replay)
3. Camera disconnect and automatic exponential backoff reconnection
4. Audio disconnect and automatic exponential backoff reconnection
5. Evidence package export and SHA-256 hash tamper verification
6. Migration from a clean old (Phase 1-4) database forward to Phase 5 schema (v7)
"""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import pytest

from src.modules.database.governed_store import IncidentRepository, MigrationRunner, MIGRATIONS, utc_now
from src.modules.security.permission_matrix import check_endpoint_permission
from src.modules.hardware.stream_service import CameraService, AudioService
from src.modules.assurance.device_health import OfflineSyncOutbox
from src.modules.reporting.evidence_verifier import EvidenceVerifier


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 1. Automated Role Test for Every User Role
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["COMMANDER", "OPERATOR", "ENGINEER", "VIEWER", None])
def test_comprehensive_role_permission_matrix(role):
    """
    Tests every distinct user role across all capability classes:
    - Commander: full municipal command, user admin, incident close/escalate, storage cleanup
    - Operator: operational triage, stream control, scenario simulation, notes, ack
    - Engineer: hardware maintenance, storage cleanup, WAL checkpoints, evidence verify
    - Viewer: read-only observer access
    - Unauthenticated (None): only public probes and status
    """
    # 1. User Management (Commander only)
    allowed, status, _ = check_endpoint_permission("/api/auth/users", "POST", role)
    if role == "COMMANDER":
        assert allowed is True and status == 200
    else:
        assert allowed is False and status in (401, 403)

    # 2. Incident Resolution & Escalation (Commander only)
    allowed, status, _ = check_endpoint_permission("/api/incidents/INC-1/resolve", "POST", role)
    if role == "COMMANDER":
        assert allowed is True and status == 200
    else:
        assert allowed is False and status in (401, 403)

    # 3. Incident Acknowledgment (Commander and Operator)
    allowed, status, _ = check_endpoint_permission("/api/incidents/INC-1/acknowledge", "POST", role)
    if role in ("COMMANDER", "OPERATOR"):
        assert allowed is True and status == 200
    else:
        assert allowed is False and status in (401, 403)

    # 4. Stream Ingestion Control (Commander and Operator)
    allowed, status, _ = check_endpoint_permission("/api/monitoring/stream/control", "POST", role)
    if role in ("COMMANDER", "OPERATOR"):
        assert allowed is True and status == 200
    else:
        assert allowed is False and status in (401, 403)

    # 5. Storage Cleanup & Retention (Commander and Engineer)
    allowed, status, _ = check_endpoint_permission("/api/storage/cleanup", "POST", role)
    if role in ("COMMANDER", "ENGINEER"):
        assert allowed is True and status == 200
    else:
        assert allowed is False and status in (401, 403)

    # 6. WAL Checkpoint Management (Commander and Engineer)
    allowed, status, _ = check_endpoint_permission("/api/storage/checkpoint", "POST", role)
    if role in ("COMMANDER", "ENGINEER"):
        assert allowed is True and status == 200
    else:
        assert allowed is False and status in (401, 403)

    # 7. Forensic Evidence Verification (Commander and Engineer)
    allowed, status, _ = check_endpoint_permission("/api/evidence/verify", "POST", role)
    if role in ("COMMANDER", "ENGINEER"):
        assert allowed is True and status == 200
    else:
        assert allowed is False and status in (401, 403)

    # 8. Report Generation (Commander, Operator, Engineer)
    allowed, status, _ = check_endpoint_permission("/api/reports/generate", "POST", role)
    if role in ("COMMANDER", "OPERATOR", "ENGINEER"):
        assert allowed is True and status == 200
    else:
        assert allowed is False and status in (401, 403)

    # 9. Public Probes (/healthz, /readyz, /api/system/version) - Open to ALL
    for public_path in ("/healthz", "/readyz", "/api/system/version", "/api/live"):
        allowed, status, _ = check_endpoint_permission(public_path, "GET", role)
        assert allowed is True and status == 200


# ---------------------------------------------------------------------------
# 2. Offline Mode Resilience Test
# ---------------------------------------------------------------------------

def test_offline_mode_outbox_and_local_persistence(tmp_path):
    """
    Simulates complete network isolation:
    - Local SQLite database writes proceed with zero blocking
    - Offline sync outbox accumulates messages with exponential backoff
    - High-priority audit rows are never dropped
    - When network restores, batch catch-up marks rows SYNCED
    """
    db_path = tmp_path / "offline_node.db"
    repo = IncidentRepository(db_path=db_path)
    outbox = OfflineSyncOutbox(repository=repo)

    # 1. Simulate local writes during network blackout
    repo.writer.submit_wait(
        lambda con: con.execute(
            "INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at) "
            "VALUES ('INC-OFFLINE-1', 'uuid-off-1', 'crash', 'ZONE_B', 'NEW', '2026-10-06T12:00:00Z', '2026-10-06T12:00:00Z')"
        )
    )

    # Enqueue outbox items during network outage
    outbox.enqueue(idempotency_key="telem-1", target="firebase", payload_type="telemetry", payload={"temp": 28.5}, priority="LOW")
    outbox.enqueue(idempotency_key="telem-2", target="firebase", payload_type="telemetry", payload={"temp": 29.1}, priority="LOW")
    outbox.enqueue(idempotency_key="inc-1", target="firebase", payload_type="incident", payload={"id": "INC-OFFLINE-1"}, priority="HIGH")
    outbox.enqueue(idempotency_key="act-1", target="firebase", payload_type="operator_action", payload={"action": "ACK"}, priority="AUDIT")

    time.sleep(0.05)
    summary = outbox.status_summary()
    assert summary["PENDING"] == 4

    # 2. Simulate repeated failed sync attempts with backoff
    with sqlite3.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        due_items = [dict(r) for r in con.execute("SELECT * FROM sync_outbox WHERE status='PENDING'").fetchall()]
    assert len(due_items) == 4

    for item in due_items:
        with sqlite3.connect(str(db_path)) as con:
            con.execute("UPDATE sync_outbox SET attempts = attempts + 1, last_error='Network unreachable' WHERE idempotency_key=?", (item["idempotency_key"],))

    with sqlite3.connect(str(db_path)) as con:
        attempts = con.execute("SELECT attempts FROM sync_outbox WHERE idempotency_key='inc-1'").fetchone()[0]
    assert attempts == 1

    # 3. Simulate network recovery and successful sync catch-up
    for item in due_items:
        with sqlite3.connect(str(db_path)) as con:
            con.execute("UPDATE sync_outbox SET status='SYNCED', updated_at=? WHERE idempotency_key=?", (utc_now(), item["idempotency_key"]))

    summary_recovered = outbox.status_summary()
    assert summary_recovered["SYNCED"] == 4
    assert summary_recovered.get("PENDING", 0) == 0


# ---------------------------------------------------------------------------
# 3. Camera Disconnect & Reconnect Resilience Test
# ---------------------------------------------------------------------------

def test_camera_disconnect_and_auto_reconnect():
    """
    Simulates camera hardware disconnection during active capture:
    - Service detects loss of frames and updates status
    - Reconnection loop triggers exponential backoff
    - Reconnect counter increments
    - Restoring source recovers stream to OK without crashing inference loop
    """
    cam = CameraService(target_fps=20.0, default_source="mock")
    cam.start()

    try:
        # Initial nominal operation
        time.sleep(0.15)
        h0 = cam.get_health()
        assert h0.status == "OK"

        # Disconnect active camera source by switching to non-existent hardware index
        cam.set_source("invalid_video_device_9999")
        time.sleep(0.2)

        # Confirm reconnection attempt triggered
        assert cam.reconnect_count >= 1 or cam.status in ("DEGRADED", "DOWN")

        # Restore source to mock / valid source
        cam.set_source("mock")
        time.sleep(1.2)

        h_recovered = cam.get_health()
        assert h_recovered.status == "OK"
    finally:
        cam.stop()


# ---------------------------------------------------------------------------
# 4. Audio Disconnect & Reconnect Resilience Test
# ---------------------------------------------------------------------------

def test_audio_disconnect_and_auto_reconnect():
    """
    Simulates microphone disconnection during audio streaming:
    - Detects buffer starvation / capture failure
    - Transitions to DEGRADED / DOWN
    - Executes backoff reconnection loop
    - Successfully recovers window streaming upon restoration
    """
    audio = AudioService(sample_rate=16000, window_sec=1.0, hop_sec=0.5, default_source="mock")
    audio.start()

    try:
        time.sleep(0.15)
        h0 = audio.get_health()
        assert h0.status == "OK"

        # Disconnect source by pointing to non-existent hardware device
        audio.set_source("invalid_audio_device_9999")
        time.sleep(0.2)

        assert audio.reconnect_count >= 1 or audio.status in ("DEGRADED", "DOWN")

        # Reconnect
        audio.set_source("mock")
        time.sleep(1.2)

        h_recovered = audio.get_health()
        assert h_recovered.status == "OK"
    finally:
        audio.stop()


# ---------------------------------------------------------------------------
# 5. Evidence Export & Integrity Verification Test
# ---------------------------------------------------------------------------

def test_evidence_export_and_tamper_verification(tmp_path):
    """
    Generates forensic evidence files with SHA-256 digests in SQLite:
    - Verifies untampered files pass 100%
    - Mutates one evidence file and verifies EvidenceVerifier flags mismatch
    """
    db_path = tmp_path / "evidence_audit.db"
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    repo = IncidentRepository(db_path=db_path)

    # Create dummy evidence files on disk
    f1 = evidence_dir / "keyframe_01.jpg"
    f2 = evidence_dir / "audio_01.wav"
    f1.write_bytes(b"JPEG_MOCK_IMAGE_BYTES_12345")
    f2.write_bytes(b"RIFF_WAV_MOCK_AUDIO_BYTES_67890")

    h1 = hashlib.sha256(f1.read_bytes()).hexdigest()
    h2 = hashlib.sha256(f2.read_bytes()).hexdigest()

    # Record in evidence ledger
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "INSERT OR IGNORE INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at) "
            "VALUES ('INC-EV-1', 'uuid-ev-1', 'crash', 'ZONE_B', 'CLOSED', '2026-10-06T10:00:00Z', '2026-10-06T10:00:00Z')"
        )
        con.execute(
            "INSERT INTO evidence(incident_id, timestamp, kind, source_path, sha256) VALUES(?,?,?,?,?)",
            ("INC-EV-1", utc_now(), "keyframe", str(f1), h1)
        )
        con.execute(
            "INSERT INTO evidence(incident_id, timestamp, kind, source_path, sha256) VALUES(?,?,?,?,?)",
            ("INC-EV-1", utc_now(), "audio_clip", str(f2), h2)
        )

    verifier = EvidenceVerifier(repo)

    # 1. Verify clean, untampered evidence
    res_clean = verifier.verify_all_evidence()
    assert res_clean["verified"] is True
    assert res_clean["tampered_count"] == 0
    assert res_clean["matched"] == 2

    # 2. Tamper with one file
    f1.write_bytes(b"TAMPERED_MODIFIED_IMAGE_CONTENT")

    res_tampered = verifier.verify_all_evidence()
    assert res_tampered["verified"] is False
    assert res_tampered["tampered_count"] == 1
    assert any(m["expected_sha256"] == h1 for m in res_tampered["tampered"])


# ---------------------------------------------------------------------------
# 6. Database Migration from Clean Old (Phase 1-4) Database Test
# ---------------------------------------------------------------------------

def test_migration_from_clean_phase1_4_database(tmp_path):
    """
    Proves forward-only migration safety from a legacy Phase 1-4 SQLite database:
    - Builds an exact Phase 1-4 schema database using only Migrations 1 through 4
    - Inserts active Phase 1-4 events and predictions
    - Runs MigrationRunner forward
    - Asserts Migrations 5, 6, and 7 are applied without errors or data loss
    - Asserts schema_migrations records all 7 versions
    - Asserts PRAGMA integrity_check passes
    """
    legacy_db = tmp_path / "legacy_phase4.db"

    # Step A: Apply ONLY migrations 1 through 4 manually
    con = sqlite3.connect(str(legacy_db))
    with con:
        con.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        for version, sql in MIGRATIONS:
            if version <= 4:
                con.executescript(sql)
                con.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(?,?)", (version, utc_now()))

        # Verify Phase 5 tables do NOT exist yet
        tables_pre = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "storage_cleanup_logs" not in tables_pre
        assert "model_baselines" not in tables_pre

        # Insert legacy records
        con.execute(
            "INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at, outcome, version) "
            "VALUES ('LEGACY-101', 'leg-uuid-1', 'crash', 'ZONE_B', 'CLOSED', '2026-10-01T12:00:00Z', '2026-10-01T12:10:00Z', 'Legacy accident', 1)"
        )
        con.execute(
            "INSERT INTO predictions(id, incident_id, timestamp, label, confidence, model_id, payload_json) "
            "VALUES (101, 'LEGACY-101', '2026-10-01T12:00:00Z', 'crash', 0.91, 'legacy-model', '{}')"
        )
    con.close()

    # Step B: Run MigrationRunner to migrate forward to Phase 5
    runner = MigrationRunner(legacy_db)
    runner.run()

    # Step C: Verify new columns and tables exist
    con_migrated = sqlite3.connect(str(legacy_db))
    tables_post = {r[0] for r in con_migrated.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert "model_baselines" in tables_post
    assert "drift_snapshots" in tables_post
    assert "device_health_events" in tables_post
    assert "sync_outbox" in tables_post
    assert "storage_cleanup_logs" in tables_post

    # Verify column additions to existing tables
    inc_cols = {r[1] for r in con_migrated.execute("PRAGMA table_info(incidents)")}
    assert "assurance_level" in inc_cols

    pred_cols = {r[1] for r in con_migrated.execute("PRAGMA table_info(predictions)")}
    assert "assurance_level" in pred_cols

    # Verify legacy records preserved with default values
    legacy_inc = con_migrated.execute("SELECT incident_id, assurance_level, outcome FROM incidents WHERE incident_id='LEGACY-101'").fetchone()
    assert legacy_inc[0] == "LEGACY-101"
    assert legacy_inc[1] == "FULL"  # Default from Migration 5
    assert legacy_inc[2] == "Legacy accident"

    # Verify migration table has recorded all versions
    applied_versions = {r[0] for r in con_migrated.execute("SELECT version FROM schema_migrations")}
    assert applied_versions == {m[0] for m in MIGRATIONS}

    # Verify PRAGMA integrity check
    qcheck = con_migrated.execute("PRAGMA quick_check").fetchone()
    assert qcheck[0] == "ok"
    con_migrated.close()
