from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from src.config.governance_config import GovernanceConfig
from src.modules.database.governed_store import IncidentRepository, MigrationRunner
from src.modules.reporting.csv_exporter import sanitize_csv_cell, stream_incidents_csv, export_incidents_csv
from src.modules.reporting.evidence_verifier import EvidenceVerifier, compute_sha256
from src.modules.reporting.report_service import ReportService, PermissionDenied
from src.modules.reporting.cli import main as cli_main


@pytest.fixture
def repo_with_data(tmp_path: Path):
    db_file = tmp_path / "test_reporting.db"
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    MigrationRunner(db_file).run()
    repo = IncidentRepository(
        db_file,
        GovernanceConfig(merge_window_seconds=120, writer_queue_size=32, evidence_root=str(evidence_dir))
    )

    now = datetime.now(timezone.utc)
    t1 = (now - timedelta(hours=5)).isoformat()
    t2 = (now - timedelta(hours=2)).isoformat()

    # Create dummy evidence files
    ev_file1 = evidence_dir / "crash_cam1.mp4"
    ev_file1.write_bytes(b"sample video bytes for crash cam 1")
    sha1 = compute_sha256(ev_file1)

    ev_file2 = evidence_dir / "siren_audio.wav"
    ev_file2.write_bytes(b"sample audio waveform bytes")
    sha2 = compute_sha256(ev_file2)

    with sqlite3.connect(db_file) as con:
        # Dangerous string in outcome/event_type to test formula injection
        con.execute(
            """
            INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status,
                                  created_at, updated_at, severity, acknowledged_seconds,
                                  resolution_seconds, assurance_level, is_demo, outcome)
            VALUES(?, 'u1', '=CMD|calc!A0', 'ZONE_A_INTERSECTION', 'RESOLVED', ?, ?, 'CRITICAL', 12.0, 95.0, 'FULL', 0, '+2+5')
            """,
            ("INC-01", t1, t1)
        )
        con.execute(
            """
            INSERT INTO incidents(incident_id, incident_uuid, event_type, zone_id, status,
                                  created_at, updated_at, severity, acknowledged_seconds,
                                  resolution_seconds, assurance_level, is_demo, outcome)
            VALUES(?, 'u2', 'COLLISION', 'ZONE_B_INTERSECTION', 'OPEN', ?, ?, 'HIGH', 18.0, NULL, 'FULL', 0, '-DDE_PAYLOAD')
            """,
            ("INC-02", t2, t2)
        )
        con.execute(
            """
            INSERT INTO predictions(id, incident_id, timestamp, label, confidence, model_id, payload_json)
            VALUES(1, 'INC-01', ?, 'FIRE', 0.96, 'edge-acoustic-net-v1', '{}')
            """,
            (t1,)
        )
        con.execute(
            """
            INSERT INTO prediction_feedback(prediction_id, label, corrected_class, operator_id, operator_role, timestamp)
            VALUES(1, 'CORRECT', NULL, 'op1', 'OPERATOR', ?)
            """,
            (t1,)
        )
        con.execute(
            """
            INSERT INTO models(model_id, name, version, sha256, held_out_f1, readiness, usage_restriction, status, created_at)
            VALUES('edge-acoustic-net-v1', 'AcousticNet', 'v1.0', 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', '0.94', 'VERIFIED', 'OPERATIONAL', 'READY', ?)
            """,
            (t1,)
        )
        con.execute(
            """
            INSERT INTO drift_snapshots(model_id, timestamp, status, reasons_json, metrics_json, sample_count, insufficient_data)
            VALUES('edge-acoustic-net-v1', ?, 'STABLE', '[]', '{"psi": 0.04}', 150, 0)
            """,
            (t1,)
        )
        con.execute(
            """
            INSERT INTO device_health_events(timestamp, component, previous_status, current_status, reason_code, message, details_json)
            VALUES(?, 'camera', 'OK', 'OK', 'nominal', 'Nominal FPS', '{}')
            """,
            (t1,)
        )
        # Register evidence records
        con.execute(
            """
            INSERT INTO evidence(id, incident_id, timestamp, kind, source_path, sha256)
            VALUES(1, 'INC-01', ?, 'video', ?, ?)
            """,
            (t1, str(ev_file1), sha1)
        )
        con.execute(
            """
            INSERT INTO evidence(id, incident_id, timestamp, kind, source_path, sha256)
            VALUES(2, 'INC-02', ?, 'audio', ?, ?)
            """,
            (t2, str(ev_file2), sha2)
        )

    yield repo, tmp_path, ev_file1, ev_file2, sha1, sha2
    repo.close()


def test_csv_formula_injection_escaping():
    """Verify cells starting with =, +, -, @, \\t, \\r are safely prefixed with single quote."""
    assert sanitize_csv_cell("=1+1") == "'=1+1"
    assert sanitize_csv_cell("+cmd|calc") == "'+cmd|calc"
    assert sanitize_csv_cell("-2+5") == "'-2+5"
    assert sanitize_csv_cell("@SUM(A1:A10)") == "'@SUM(A1:A10)"
    assert sanitize_csv_cell("\tTabbed") == "'\tTabbed"
    assert sanitize_csv_cell("Normal text") == "Normal text"
    assert sanitize_csv_cell(123) == "123"
    assert sanitize_csv_cell(None) == ""


def test_incident_csv_export_streaming(repo_with_data):
    repo, tmp_path, _, _, _, _ = repo_with_data
    out_csv = tmp_path / "exports" / "test_incidents.csv"
    export_incidents_csv(repo, out_csv)

    assert out_csv.exists()
    content = out_csv.read_text(encoding="utf-8")
    lines = content.strip().splitlines()
    assert len(lines) == 3  # Header + 2 incident rows

    reader = csv.reader(lines)
    header = next(reader)
    assert "incident_id" in header
    assert "event_type" in header

    # Ensure dangerous payloads were neutralized
    rows = list(reader)
    event_types = [r[header.index("event_type")] for r in rows]
    outcomes = [r[header.index("outcome")] for r in rows]

    # Verify prefixed with single-quote
    assert any(et.startswith("'=") for et in event_types)
    assert any(o.startswith("'+") or o.startswith("'-") for o in outcomes)


def test_monthly_operations_report_generation(repo_with_data):
    repo, tmp_path, _, _, _, _ = repo_with_data
    rep_dir = tmp_path / "reports"
    svc = ReportService(repo, reports_dir=rep_dir)

    res = svc.generate(report_type="monthly", month="2026-10", role="COMMANDER")
    assert res["status"] == "SUCCESS"
    assert Path(res["path"]).exists()
    html_content = Path(res["html_path"]).read_text(encoding="utf-8")

    assert "Monthly Operations Report - 2026-10" in html_content
    assert "ZONE_A_INTERSECTION" in html_content
    assert "Total Incidents" in html_content

    # Manifest check
    manifest = svc.list_reports()
    assert len(manifest) >= 1
    assert manifest[-1]["report_type"] == "monthly"


def test_model_assurance_and_drift_reports(repo_with_data):
    repo, tmp_path, _, _, _, _ = repo_with_data
    rep_dir = tmp_path / "reports"
    svc = ReportService(repo, reports_dir=rep_dir)

    # Model assurance
    res_ass = svc.generate(report_type="assurance", role="COMMANDER")
    assert res_ass["status"] == "SUCCESS"
    html_ass = Path(res_ass["html_path"]).read_text(encoding="utf-8")
    assert "Model Assurance & Verification Report" in html_ass
    assert "edge-acoustic-net-v1" in html_ass

    # Drift report
    res_drift = svc.generate(report_type="drift", role="COMMANDER")
    assert res_drift["status"] == "SUCCESS"
    html_drift = Path(res_drift["html_path"]).read_text(encoding="utf-8")
    assert "Model Drift Monitoring Report" in html_drift
    assert "STABLE" in html_drift


def test_device_health_and_evidence_index_reports(repo_with_data):
    repo, tmp_path, _, _, _, _ = repo_with_data
    rep_dir = tmp_path / "reports"
    svc = ReportService(repo, reports_dir=rep_dir)

    # Health report
    res_health = svc.generate(report_type="health", role="ENGINEER")
    assert res_health["status"] == "SUCCESS"
    html_health = Path(res_health["html_path"]).read_text(encoding="utf-8")
    assert "Device Health & Availability Report" in html_health
    assert "camera" in html_health

    # Evidence index
    res_ev = svc.generate(report_type="evidence", role="COMMANDER")
    assert res_ev["status"] == "SUCCESS"
    html_ev = Path(res_ev["html_path"]).read_text(encoding="utf-8")
    assert "Forensic Evidence Package Index" in html_ev
    assert "crash_cam1.mp4" in html_ev


def test_pdf_report_generation(repo_with_data):
    repo, tmp_path, _, _, _, _ = repo_with_data
    rep_dir = tmp_path / "reports"
    svc = ReportService(repo, reports_dir=rep_dir)

    # PDF generation
    res = svc.generate(report_type="monthly", month="2026-10", as_pdf=True, role="COMMANDER")
    assert res["status"] == "SUCCESS"
    assert Path(res["path"]).exists()
    assert res["report"]["format"] == "pdf"
    assert Path(res["path"]).suffix == ".pdf"


def test_report_role_permissions(repo_with_data):
    repo, tmp_path, _, _, _, _ = repo_with_data
    rep_dir = tmp_path / "reports"
    svc = ReportService(repo, reports_dir=rep_dir)

    # Operator can generate monthly and csv
    res_op = svc.generate(report_type="monthly", role="OPERATOR")
    assert res_op["status"] == "SUCCESS"

    # Operator cannot generate assurance or evidence
    with pytest.raises(PermissionDenied):
        svc.generate(report_type="assurance", role="OPERATOR")

    with pytest.raises(PermissionDenied):
        svc.generate(report_type="evidence", role="OPERATOR")

    # Engineer can generate drift and health, but not monthly
    res_eng = svc.generate(report_type="drift", role="ENGINEER")
    assert res_eng["status"] == "SUCCESS"
    with pytest.raises(PermissionDenied):
        svc.generate(report_type="monthly", role="ENGINEER")

    # Viewer cannot generate anything
    with pytest.raises(PermissionDenied):
        svc.generate(report_type="monthly", role="VIEWER")
    with pytest.raises(PermissionDenied):
        svc.generate(report_type="csv", role="VIEWER")


def test_evidence_verification_and_tamper_detection(repo_with_data):
    repo, tmp_path, ev_file1, ev_file2, sha1, sha2 = repo_with_data
    verifier = EvidenceVerifier(repo)

    # 1. Clean state: all files match
    clean_check = verifier.verify_all_evidence()
    assert clean_check["verified"] is True
    assert clean_check["total_checked"] == 2
    assert clean_check["matched"] == 2
    assert clean_check["tampered_count"] == 0
    assert clean_check["missing_count"] == 0

    # 2. Tamper ev_file1
    ev_file1.write_bytes(b"tampered malicious video content payload")
    tamper_check = verifier.verify_all_evidence()
    assert tamper_check["verified"] is False
    assert tamper_check["matched"] == 1
    assert tamper_check["tampered_count"] == 1
    assert tamper_check["tampered"][0]["id"] == 1
    assert tamper_check["tampered"][0]["expected_sha256"] == sha1

    # 3. Missing file
    ev_file2.unlink()
    missing_check = verifier.verify_all_evidence()
    assert missing_check["verified"] is False
    assert missing_check["missing_count"] == 1
    assert missing_check["missing"][0]["id"] == 2


def test_cli_generate_and_verify(tmp_path: Path, monkeypatch):
    """Test CLI commands: generate monthly report and verify evidence."""
    db_file = tmp_path / "cli_test.db"
    MigrationRunner(db_file).run()
    from src.config.settings import CONFIG
    monkeypatch.setattr(CONFIG, "db_path", str(db_file))

    rep_dir = tmp_path / "cli_reports"

    # Test CLI generate
    ret_gen = cli_main(["generate", "--type", "monthly", "--month", "2026-10", "--output-dir", str(rep_dir)])
    assert ret_gen == 0
    assert (rep_dir / "operations_report_2026-10.html").exists()

    # Test CLI verify
    ret_ver = cli_main(["verify-evidence"])
    assert ret_ver == 0

    # Test CLI list
    ret_list = cli_main(["list"])
    assert ret_list == 0
