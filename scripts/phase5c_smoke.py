#!/usr/bin/env python3
"""Phase 5C Reporting & Exports Smoke Test and Verification.

Validates:
1. Streamed incident CSV export with CSV/formula injection sanitization.
2. Generation of all 5 report types:
   - Monthly Operations Report
   - Model Assurance & Verification Report
   - Model Drift Monitoring Report
   - Device Health & Availability Report
   - Forensic Evidence Package Index
3. Print-friendly HTML templates and ReportLab PDF fallback.
4. Cryptographic report manifest and audit logging.
5. Evidence re-hashing and tamper detection engine.
6. Role-based access control rules.
7. CLI entrypoint invocation.
"""
from __future__ import annotations

import csv
import gc
import io
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.governance_config import GovernanceConfig
from src.modules.database.governed_store import IncidentRepository, MigrationRunner
from src.modules.reporting.csv_exporter import sanitize_csv_cell, stream_incidents_csv, export_incidents_csv
from src.modules.reporting.evidence_verifier import EvidenceVerifier, compute_sha256
from src.modules.reporting.report_service import ReportService, PermissionDenied
from src.modules.reporting.cli import main as cli_main


def run_phase5c_smoke() -> bool:
    print("=" * 70)
    print(" SENTINEL-AI PHASE 5C: REPORTING & EXPORTS SMOKE VERIFICATION")
    print("=" * 70)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_path = Path(tmpdir)
        db_file = tmp_path / "smoke_reports.db"
        reports_dir = tmp_path / "reports"
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)

        print("\n[Step 1] Initializing SQLite schema and migrations...")
        MigrationRunner(db_file).run()
        repo = IncidentRepository(
            db_file,
            GovernanceConfig(merge_window_seconds=120, writer_queue_size=32, evidence_root=str(evidence_dir))
        )

        now = datetime.now(timezone.utc)
        t1 = (now - timedelta(days=2)).isoformat()
        t2 = (now - timedelta(days=1)).isoformat()

        # Create physical evidence files
        video_file = evidence_dir / "crash_evidence_01.mp4"
        video_file.write_bytes(b"Simulated crash dashcam H.264 stream bytes.")
        sha_video = compute_sha256(video_file)

        audio_file = evidence_dir / "acoustic_sensor_01.wav"
        audio_file.write_bytes(b"Simulated siren acoustic PCM waveform bytes.")
        sha_audio = compute_sha256(audio_file)

        print("[Step 2] Seeding test database with incidents, evidence & formula injection payloads...")
        con = sqlite3.connect(db_file)
        try:
            # Seed dangerous payloads: cells starting with =, +, -, @, \t
            con.execute(
                """
                INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status,
                                      created_at, updated_at, severity, acknowledged_seconds,
                                      resolution_seconds, assurance_level, is_demo, outcome)
                VALUES(?, 'u1', '=CMD|calc!A0', 'ZONE_NORTH', 'RESOLVED', ?, ?, 'CRITICAL', 14.5, 82.0, 'FULL', 0, '+2+5')
                """,
                ("INC-2026-0001", t1, t1)
            )
            con.execute(
                """
                INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status,
                                      created_at, updated_at, severity, acknowledged_seconds,
                                      resolution_seconds, assurance_level, is_demo, outcome)
                VALUES(?, 'u2', 'COLLISION', 'ZONE_SOUTH', 'OPEN', ?, ?, 'HIGH', 19.0, NULL, 'FULL', 0, '-DDE_PAYLOAD')
                """,
                ("INC-2026-0002", t2, t2)
            )
            con.execute(
                """
                INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status,
                                      created_at, updated_at, severity, acknowledged_seconds,
                                      resolution_seconds, assurance_level, is_demo, outcome)
                VALUES(?, 'u3', '@SUM(A1:A10)', 'ZONE_EAST', 'FALSE_ALARM', ?, ?, 'LOW', 25.0, 45.0, 'DEGRADED', 0, '\tTabInjection')
                """,
                ("INC-2026-0003", t2, t2)
            )

            # Predictions and feedback
            con.execute(
                """
                INSERT INTO predictions(id, incident_id, timestamp, label, confidence, model_id, payload_json)
                VALUES(1, 'INC-2026-0001', ?, 'FIRE', 0.95, 'edge-vision-yolo11n', '{}')
                """,
                (t1,)
            )
            con.execute(
                """
                INSERT INTO prediction_feedback(prediction_id, label, corrected_class, operator_id, operator_role, timestamp)
                VALUES(1, 'CORRECT', NULL, 'commander1', 'COMMANDER', ?)
                """,
                (t1,)
            )

            # Model registry
            con.execute(
                """
                INSERT INTO models(model_id, name, version, sha256, held_out_f1, readiness, usage_restriction, status, created_at)
                VALUES('edge-vision-yolo11n', 'YOLO11n-Edge', 'v1.0', '9f83...hash', '0.92', 'VERIFIED', 'OPERATIONAL', 'READY', ?)
                """,
                (t1,)
            )

            # Drift snapshot
            con.execute(
                """
                INSERT INTO drift_snapshots(model_id, timestamp, status, reasons_json, metrics_json, sample_count, insufficient_data)
                VALUES('edge-vision-yolo11n', ?, 'STABLE', '[]', '{"psi": 0.024}', 320, 0)
                """,
                (t1,)
            )

            # Device health event
            con.execute(
                """
                INSERT INTO device_health_events(timestamp, component, previous_status, current_status, reason_code, message, details_json)
                VALUES(?, 'camera', 'OK', 'OK', 'nominal', 'FPS stable at 29.8', '{}')
                """,
                (t1,)
            )

            # Evidence ledger records
            con.execute(
                """
                INSERT INTO evidence(id, incident_id, timestamp, kind, source_path, sha256)
                VALUES(1, 'INC-2026-0001', ?, 'video', ?, ?)
                """,
                (t1, str(video_file), sha_video)
            )
            con.execute(
                """
                INSERT INTO evidence(id, incident_id, timestamp, kind, source_path, sha256)
                VALUES(2, 'INC-2026-0002', ?, 'audio', ?, ?)
                """,
                (t2, str(audio_file), sha_audio)
            )
            con.commit()
        finally:
            con.close()

        print("  -> Seed complete: 3 incidents, 2 evidence records, 1 model, 1 drift snapshot.")

        # [Test 1] CSV Formula Injection Sanitization
        print("\n[Step 3] Validating CSV formula injection escaping...")
        assert sanitize_csv_cell("=1+1") == "'=1+1"
        assert sanitize_csv_cell("+cmd|calc") == "'+cmd|calc"
        assert sanitize_csv_cell("-2+5") == "'-2+5"
        assert sanitize_csv_cell("@SUM(A1:A10)") == "'@SUM(A1:A10)"
        assert sanitize_csv_cell("\tTabPayload") == "'\tTabPayload"
        assert sanitize_csv_cell("Normal Text") == "Normal Text"
        print("  -> sanitize_csv_cell correctly prefixes dangerous formula triggers.")

        # [Test 2] Streamed CSV Export
        print("\n[Step 4] Validating streamed incident CSV export...")
        csv_out = tmp_path / "test_export.csv"
        export_incidents_csv(repo, csv_out)
        assert csv_out.exists(), "CSV output file not created"

        content = csv_out.read_text(encoding="utf-8")
        reader = list(csv.reader(content.strip().splitlines()))
        header = reader[0]
        rows = reader[1:]
        assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}"

        # Verify cells starting with =, +, -, @, \t are safely sanitized
        event_col = header.index("event_type")
        outcome_col = header.index("outcome")
        assert any(r[event_col].startswith("'=") for r in rows), "Expected sanitized = formula"
        assert any(r[event_col].startswith("'@") for r in rows), "Expected sanitized @ formula"
        assert any(r[outcome_col].startswith("'+") or r[outcome_col].startswith("'-") for r in rows), "Expected sanitized +/- formula"
        print("  -> CSV export successfully streamed and sanitized against formula execution.")

        # [Test 3] Report Generation Service
        print("\n[Step 5] Validating ReportService generation for all report types...")
        svc = ReportService(repo, reports_dir=reports_dir)

        # 1. Monthly operations report
        res_monthly = svc.generate(report_type="monthly", month="2026-10", role="COMMANDER")
        assert res_monthly["status"] == "SUCCESS"
        assert Path(res_monthly["html_path"]).exists()
        print(f"  -> Monthly Report: {Path(res_monthly['html_path']).name} (SHA: {res_monthly['report']['sha256'][:12]}...)")

        # 2. Model assurance report
        res_ass = svc.generate(report_type="assurance", role="COMMANDER")
        assert res_ass["status"] == "SUCCESS"
        assert Path(res_ass["html_path"]).exists()
        print(f"  -> Model Assurance Report: {Path(res_ass['html_path']).name}")

        # 3. Model drift report
        res_drift = svc.generate(report_type="drift", role="ENGINEER")
        assert res_drift["status"] == "SUCCESS"
        assert Path(res_drift["html_path"]).exists()
        print(f"  -> Model Drift Report: {Path(res_drift['html_path']).name}")

        # 4. Device health report
        res_health = svc.generate(report_type="health", role="ENGINEER")
        assert res_health["status"] == "SUCCESS"
        assert Path(res_health["html_path"]).exists()
        print(f"  -> Device Health Report: {Path(res_health['html_path']).name}")

        # 5. Evidence package index
        res_ev = svc.generate(report_type="evidence", role="COMMANDER")
        assert res_ev["status"] == "SUCCESS"
        assert Path(res_ev["html_path"]).exists()
        print(f"  -> Evidence Index: {Path(res_ev['html_path']).name}")

        # Check manifest
        reports = svc.list_reports()
        assert len(reports) == 5, f"Expected 5 reports in manifest, found {len(reports)}"
        print(f"  -> Reports manifest verified: {len(reports)} entries logged.")

        # [Test 4] PDF Generation & Fallback
        print("\n[Step 6] Validating PDF generation...")
        res_pdf = svc.generate(report_type="monthly", month="2026-10", as_pdf=True, role="COMMANDER")
        assert res_pdf["status"] == "SUCCESS"
        assert Path(res_pdf["path"]).exists()
        print(f"  -> PDF generation verified: {Path(res_pdf['path']).name} (Format: {res_pdf['report']['format']})")

        # [Test 5] Role Permissions
        print("\n[Step 7] Validating Role-Based Access Control...")
        # Operator cannot generate assurance
        try:
            svc.generate(report_type="assurance", role="OPERATOR")
            raise AssertionError("OPERATOR should not be allowed to generate assurance report")
        except PermissionDenied:
            print("  -> RBAC check passed: OPERATOR denied assurance report access.")

        # Viewer cannot generate monthly report
        try:
            svc.generate(report_type="monthly", role="VIEWER")
            raise AssertionError("VIEWER should not be allowed to generate monthly report")
        except PermissionDenied:
            print("  -> RBAC check passed: VIEWER denied monthly report access.")

        # [Test 6] Evidence Tamper Detection
        print("\n[Step 8] Validating EvidenceVerifier integrity and tamper detection...")
        verifier = EvidenceVerifier(repo)

        # Baseline: all match
        check1 = verifier.verify_all_evidence()
        assert check1["verified"] is True
        assert check1["matched"] == 2
        assert check1["tampered_count"] == 0
        print("  -> Clean baseline verified: 2/2 files matched.")

        # Tampering video file
        video_file.write_bytes(b"Tampered payload data overwriting original evidence.")
        check2 = verifier.verify_all_evidence()
        assert check2["verified"] is False
        assert check2["tampered_count"] == 1
        assert check2["tampered"][0]["id"] == 1
        print(f"  -> Tamper detected successfully: Record ID {check2['tampered'][0]['id']} flagged mismatch.")

        # Missing audio file
        audio_file.unlink()
        check3 = verifier.verify_all_evidence()
        assert check3["verified"] is False
        assert check3["missing_count"] == 1
        print(f"  -> Missing file detected successfully: Record ID {check3['missing'][0]['id']} flagged missing.")

        # [Test 7] CLI Invocation
        print("\n[Step 9] Validating CLI entrypoint...")
        from src.config.settings import CONFIG
        CONFIG.db_path = str(db_file)
        ret = cli_main(["generate", "--type", "monthly", "--month", "2026-10", "--output-dir", str(reports_dir)])
        assert ret == 0, f"CLI generate returned non-zero code: {ret}"
        print("  -> CLI 'generate' completed successfully.")

        ret_ver = cli_main(["verify-evidence"])
        # Exit code may be non-zero since we tampered files earlier
        print(f"  -> CLI 'verify-evidence' ran (status code {ret_ver} reflecting tamper detection).")

        repo.close()
        del repo, verifier, svc
        gc.collect()

    print("\n" + "=" * 70)
    print(" ALL PHASE 5C VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = run_phase5c_smoke()
    sys.exit(0 if success else 1)
