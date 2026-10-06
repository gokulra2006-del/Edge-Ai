from __future__ import annotations
from pathlib import Path
import sqlite3
import time

from src.config.governance_config import GovernanceConfig
from src.modules.database.governed_store import EvidenceExporter, IncidentRepository, MigrationRunner, ModelRegistry


def repo(tmp_path):
    return IncidentRepository(tmp_path / "governed.db", GovernanceConfig(merge_window_seconds=120, writer_queue_size=32, evidence_root=str(tmp_path / "evidence")))


def test_migrations_rerun_and_legacy_upgrade(tmp_path):
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE emergency_events (id INTEGER PRIMARY KEY, event_type TEXT, zone_id TEXT, timestamp TEXT)")
        con.execute("INSERT INTO emergency_events VALUES(1,'collision','Z1','2026-10-05T00:00:00+00:00')")
    MigrationRunner(db).run(); MigrationRunner(db).run()
    with sqlite3.connect(db) as con:
        from src.modules.database.governed_store import MIGRATIONS
        assert con.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == len(MIGRATIONS)
        assert con.execute("SELECT incident_id FROM incidents WHERE incident_id='LEGACY-1'").fetchone()[0] == "LEGACY-1"
        assert con.execute("SELECT event_type FROM emergency_events").fetchone()[0] == "collision"


def test_incident_merge_and_duplicate_suppression(tmp_path):
    r = repo(tmp_path)
    try:
        a, merged = r.create_incident("collision", "Z1", "2026-10-05T00:00:00+00:00")
        r.writer.drain()
        b, merged = r.create_incident("collision", "Z1", "2026-10-05T00:01:00+00:00")
        assert a == b and merged
        c, merged = r.create_incident("collision", "Z1", "2026-10-05T00:03:00+00:00")
        assert c != a and not merged
        r.add_event(a, "trigger", {"x": 1}, dedupe_key="same")
        r.add_event(a, "trigger", {"x": 1}, dedupe_key="same")
        assert r.writer.drain()
        assert len(r.rows("incident_events", a)) == 1
    finally: r.close()


def test_writer_survives_locked_database(tmp_path):
    r = repo(tmp_path)
    try:
        incident, _ = r.create_incident("fire", "Z2")
        r.writer.drain()
        lock = sqlite3.connect(r.db_path); lock.execute("BEGIN EXCLUSIVE")
        assert r.add_event(incident, "trigger", {"locked": True})
        time.sleep(.1)
        lock.rollback(); lock.close()
        assert r.writer.drain(4)
        assert r.writer.health()["healthy"]
    finally: r.close()


def test_evidence_export_and_tamper_detection(tmp_path):
    r = repo(tmp_path)
    try:
        incident, _ = r.create_incident("collision", "Z3")
        r.writer.drain(); clip = tmp_path / "trigger.wav"; clip.write_bytes(b"audio")
        r.attach_evidence(incident, "audio", clip); r.add_prediction(incident, "collision", .91, "m1")
        r.add_operator_action(incident, "operator", "approve_contact", True); r.close_incident(incident, "operator approved")
        exporter = EvidenceExporter(r, tmp_path / "evidence")
        manifest = exporter.export(incident)
        assert manifest.exists() and manifest.parent.with_suffix(".zip").exists()
        assert exporter.verify(manifest)
        (manifest.parent / "files" / "trigger.wav").write_bytes(b"tampered")
        assert not exporter.verify(manifest)
    finally: r.close()


def test_registry_checksum_mismatch_sets_review_required(tmp_path):
    r = repo(tmp_path)
    try:
        model = tmp_path / "model.bin"; model.write_bytes(b"original")
        registry = ModelRegistry(r); registry.register("m1", "test", "1", model, "UNVERIFIED", "UNVERIFIED")
        r.writer.drain(); model.write_bytes(b"changed")
        assert not registry.verify_on_startup("m1", model)
        r.writer.drain()
        assert r._read("SELECT status FROM models WHERE model_id='m1'")[0]["status"] == "REVIEW_REQUIRED"
        assert r._read("SELECT status FROM deployments WHERE model_id='m1'")[0]["status"] == "REVIEW_REQUIRED"
    finally: r.close()
