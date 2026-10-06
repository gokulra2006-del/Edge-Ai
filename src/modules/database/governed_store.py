"""Governed incident persistence.  SQLite writes are isolated from inference."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
import queue
import shutil
import sqlite3
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from src.config.governance_config import GovernanceConfig, load_governance_config


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CONFIRMED = "CONFIRMED"
    ESCALATED = "ESCALATED"
    FALSE_ALARM = "FALSE_ALARM"
    CLOSED = "CLOSED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


_WRITER_FAILURES: list[str] = []

def writer_health_snapshot() -> dict[str, Any]:
    return {"healthy": not _WRITER_FAILURES, "failures": list(_WRITER_FAILURES)}

MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, """
    CREATE TABLE IF NOT EXISTS incidents (
      incident_id TEXT PRIMARY KEY, incident_uuid TEXT NOT NULL UNIQUE,
      event_type TEXT NOT NULL, zone_id TEXT NOT NULL, status TEXT NOT NULL,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, outcome TEXT
    );
    CREATE TABLE IF NOT EXISTS incident_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL,
      timestamp TEXT NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
      dedupe_key TEXT, FOREIGN KEY(incident_id) REFERENCES incidents(incident_id)
    );
    CREATE TABLE IF NOT EXISTS predictions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL,
      timestamp TEXT NOT NULL, label TEXT NOT NULL, confidence REAL NOT NULL,
      model_id TEXT, payload_json TEXT NOT NULL,
      FOREIGN KEY(incident_id) REFERENCES incidents(incident_id)
    );
    CREATE TABLE IF NOT EXISTS operator_actions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL,
      timestamp TEXT NOT NULL, operator_id TEXT NOT NULL, action TEXT NOT NULL,
      approved INTEGER NOT NULL DEFAULT 0, payload_json TEXT NOT NULL,
      FOREIGN KEY(incident_id) REFERENCES incidents(incident_id)
    );
    CREATE TABLE IF NOT EXISTS evidence (
      id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL,
      timestamp TEXT NOT NULL, kind TEXT NOT NULL, source_path TEXT NOT NULL,
      sha256 TEXT NOT NULL, FOREIGN KEY(incident_id) REFERENCES incidents(incident_id)
    );
    CREATE TABLE IF NOT EXISTS assurance_states (
      id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT, timestamp TEXT NOT NULL,
      model_id TEXT, state TEXT NOT NULL, payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS models (
      model_id TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL,
      sha256 TEXT, held_out_f1 TEXT NOT NULL, readiness TEXT NOT NULL,
      usage_restriction TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS deployments (
      id INTEGER PRIMARY KEY AUTOINCREMENT, model_id TEXT NOT NULL, timestamp TEXT NOT NULL,
      event TEXT NOT NULL, status TEXT NOT NULL, details_json TEXT NOT NULL,
      FOREIGN KEY(model_id) REFERENCES models(model_id)
    );
    CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
    CREATE INDEX IF NOT EXISTS idx_incidents_zone ON incidents(zone_id);
    CREATE INDEX IF NOT EXISTS idx_events_incident ON incident_events(incident_id);
    CREATE INDEX IF NOT EXISTS idx_events_timestamp ON incident_events(timestamp);
    CREATE INDEX IF NOT EXISTS idx_predictions_incident ON predictions(incident_id);
    CREATE INDEX IF NOT EXISTS idx_predictions_timestamp ON predictions(timestamp);
    CREATE INDEX IF NOT EXISTS idx_evidence_incident ON evidence(incident_id);
    """),
    (2, """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_events_dedupe
      ON incident_events(incident_id, dedupe_key) WHERE dedupe_key IS NOT NULL;
    """),
    (3, """
    ALTER TABLE incidents ADD COLUMN risk_level TEXT;
    ALTER TABLE incidents ADD COLUMN risk_breakdown_json TEXT;
    """),
    (4, """
    ALTER TABLE incidents ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE incidents ADD COLUMN acknowledged_seconds REAL;
    ALTER TABLE incidents ADD COLUMN resolution_seconds REAL;
    ALTER TABLE incidents ADD COLUMN temporal_state TEXT;
    ALTER TABLE incidents ADD COLUMN ood_status TEXT;
    ALTER TABLE incidents ADD COLUMN ood_reasons_json TEXT;
    ALTER TABLE incidents ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE incidents ADD COLUMN severity TEXT;
    CREATE TABLE IF NOT EXISTS incident_notes (
      id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL,
      timestamp TEXT NOT NULL, operator_id TEXT NOT NULL, operator_role TEXT NOT NULL,
      note TEXT NOT NULL, FOREIGN KEY(incident_id) REFERENCES incidents(incident_id)
    );
    CREATE TABLE IF NOT EXISTS prediction_feedback (
      id INTEGER PRIMARY KEY AUTOINCREMENT, prediction_id INTEGER NOT NULL,
      label TEXT NOT NULL, corrected_class TEXT, operator_id TEXT NOT NULL,
      operator_role TEXT NOT NULL, timestamp TEXT NOT NULL, comment TEXT,
      FOREIGN KEY(prediction_id) REFERENCES predictions(id)
    );
    CREATE TABLE IF NOT EXISTS review_claims (
      prediction_id INTEGER PRIMARY KEY, operator_id TEXT NOT NULL,
      operator_role TEXT NOT NULL, claimed_at TEXT NOT NULL,
      FOREIGN KEY(prediction_id) REFERENCES predictions(id)
    );
    CREATE INDEX IF NOT EXISTS idx_feedback_prediction ON prediction_feedback(prediction_id);
    CREATE INDEX IF NOT EXISTS idx_notes_incident ON incident_notes(incident_id);
    """),
    (5, """
    ALTER TABLE incidents ADD COLUMN assurance_level TEXT NOT NULL DEFAULT 'FULL';
    ALTER TABLE predictions ADD COLUMN assurance_level TEXT NOT NULL DEFAULT 'FULL';
    CREATE TABLE IF NOT EXISTS model_baselines (
      model_id TEXT PRIMARY KEY,
      confidence_histogram_json TEXT NOT NULL,
      ood_rate REAL NOT NULL,
      class_prior_json TEXT NOT NULL,
      false_alarm_rate REAL NOT NULL,
      source TEXT NOT NULL,
      sample_count INTEGER NOT NULL,
      usage_restriction TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS drift_snapshots (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      model_id TEXT NOT NULL,
      timestamp TEXT NOT NULL,
      status TEXT NOT NULL,
      reasons_json TEXT NOT NULL,
      metrics_json TEXT NOT NULL,
      sample_count INTEGER NOT NULL,
      insufficient_data INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_drift_snapshots_model ON drift_snapshots(model_id, timestamp);
    CREATE TABLE IF NOT EXISTS device_health_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      timestamp TEXT NOT NULL,
      component TEXT NOT NULL,
      previous_status TEXT,
      current_status TEXT NOT NULL,
      reason_code TEXT NOT NULL,
      message TEXT NOT NULL,
      details_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_health_events_comp ON device_health_events(component, timestamp);
    CREATE TABLE IF NOT EXISTS sync_outbox (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      idempotency_key TEXT NOT NULL UNIQUE,
      target TEXT NOT NULL,
      payload_type TEXT NOT NULL,
      payload_ref TEXT,
      payload_json TEXT NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0,
      next_attempt_at TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'PENDING',
      priority TEXT NOT NULL DEFAULT 'NORMAL',
      last_error TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_sync_outbox_status ON sync_outbox(status, next_attempt_at);
    """),
    (6, """
    CREATE INDEX IF NOT EXISTS idx_incidents_created_at ON incidents(created_at);
    CREATE INDEX IF NOT EXISTS idx_incidents_event_type ON incidents(event_type);
    CREATE INDEX IF NOT EXISTS idx_predictions_model_ts ON predictions(model_id, timestamp);
    CREATE INDEX IF NOT EXISTS idx_feedback_ts ON prediction_feedback(timestamp);
    CREATE INDEX IF NOT EXISTS idx_operator_actions_ts ON operator_actions(timestamp);
    """),
)


def _connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path), timeout=1.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=1000")
    return con


class MigrationRunner:
    def __init__(self, db_path: Path): self.db_path = Path(db_path)
    def run(self) -> None:
        with _connection(self.db_path) as con:
            con.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            done = {r[0] for r in con.execute("SELECT version FROM schema_migrations")}
            for version, sql in MIGRATIONS:
                if version not in done:
                    with con:
                        con.executescript(sql)
                        con.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(?,?)", (version, utc_now()))
            self._bridge_legacy(con)
    def _bridge_legacy(self, con: sqlite3.Connection) -> None:
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "emergency_events" not in names: return
        columns = {r[1] for r in con.execute("PRAGMA table_info(emergency_events)")}
        if not {"id", "event_type"}.issubset(columns): return
        for row in con.execute("SELECT * FROM emergency_events"):
            old_id = row["id"]
            incident_id = f"LEGACY-{old_id}"
            timestamp = row["timestamp"] if "timestamp" in columns and row["timestamp"] else utc_now()
            zone = row["zone_id"] if "zone_id" in columns and row["zone_id"] else "LEGACY"
            con.execute("INSERT OR IGNORE INTO incidents(incident_id,incident_uuid,event_type,zone_id,status,created_at,updated_at,outcome) VALUES(?,?,?,?,?,?,?,?)", (incident_id, str(uuid4()), row["event_type"], zone, IncidentStatus.CLOSED.value, timestamp, timestamp, "Migrated legacy event"))


class SQLiteWriter:
    """Single daemon writer. Failures never stop callers or the worker."""
    def __init__(self, db_path: Path, maxsize: int = 256):
        self.db_path, self.queue = Path(db_path), queue.Queue(maxsize=maxsize)
        self.failures: list[str] = []; self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="incident-db-writer")
        self.thread.start()
    def submit(self, operation: Callable[[sqlite3.Connection], None]) -> bool:
        try: self.queue.put_nowait(operation); return True
        except queue.Full: self.failures.append("writer queue full"); _WRITER_FAILURES.append("writer queue full"); return False
    def submit_wait(self, operation: Callable[[sqlite3.Connection], Any], timeout: float = 3.0) -> Any:
        completed = threading.Event(); result: dict[str, Any] = {}
        def wrapped(connection: sqlite3.Connection) -> None:
            try: result["value"] = operation(connection)
            except Exception as exc: result["error"] = exc
            finally: completed.set()
        if not self.submit(wrapped): raise RuntimeError("writer queue unavailable")
        if not completed.wait(timeout): raise TimeoutError("database writer timed out")
        if "error" in result: raise result["error"]
        return result.get("value")
    def _run(self) -> None:
        while not self._stop.is_set() or not self.queue.empty():
            try: op = self.queue.get(timeout=.1)
            except queue.Empty: continue
            try:
                for attempt in range(4):
                    try:
                        with _connection(self.db_path) as con: op(con)
                        break
                    except sqlite3.OperationalError as exc:
                        if "locked" not in str(exc).lower() or attempt == 3: raise
                        time.sleep(.05 * (2 ** attempt))
            except Exception as exc:
                failure = f"{type(exc).__name__}: {exc}"
                self.failures.append(failure); _WRITER_FAILURES.append(failure)
            finally: self.queue.task_done()
    def drain(self, timeout: float = 3.0) -> bool:
        end = time.monotonic() + timeout
        while self.queue.unfinished_tasks and time.monotonic() < end: time.sleep(.01)
        return not self.queue.unfinished_tasks
    def health(self) -> dict[str, Any]: return {"healthy": not self.failures, "failures": list(self.failures), "queued": self.queue.qsize()}
    def close(self) -> None: self._stop.set(); self.thread.join(timeout=2)


class IncidentRepository:
    def __init__(self, db_path: Path, config: GovernanceConfig | None = None):
        self.db_path = Path(db_path); self.config = config or load_governance_config()
        MigrationRunner(self.db_path).run(); self.writer = SQLiteWriter(self.db_path, self.config.writer_queue_size)
    def _read(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with _connection(self.db_path) as con: return list(con.execute(sql, args))
    def create_incident(self, event_type: str, zone_id: str, timestamp: str | None = None, assurance_level: str = "FULL") -> tuple[str, bool]:
        timestamp = timestamp or utc_now()
        cutoff = datetime.fromisoformat(timestamp).timestamp() - self.config.merge_window_seconds
        for row in self._read("SELECT incident_id, created_at FROM incidents WHERE event_type=? AND zone_id=? AND status<>? ORDER BY created_at DESC", (event_type, zone_id, IncidentStatus.CLOSED.value)):
            if datetime.fromisoformat(row["created_at"]).timestamp() >= cutoff: return row["incident_id"], True
        day = timestamp[:10].replace("-", "")
        seq = len(self._read("SELECT incident_id FROM incidents WHERE incident_id LIKE ?", (f"INC-{day}-%",))) + 1
        incident_id = f"INC-{day}-{seq:04d}"; incident_uuid = str(uuid4())
        self.writer.submit(lambda c: c.execute("INSERT INTO incidents(incident_id,incident_uuid,event_type,zone_id,status,created_at,updated_at,outcome,assurance_level) VALUES(?,?,?,?,?,?,?,?,?)", (incident_id, incident_uuid, event_type, zone_id, IncidentStatus.OPEN.value, timestamp, timestamp, None, assurance_level)))
        return incident_id, False
    def add_event(self, incident_id: str, event_type: str, payload: dict[str, Any], timestamp: str | None = None, dedupe_key: str | None = None) -> bool:
        ts = timestamp or utc_now(); body = json.dumps(payload, sort_keys=True)
        return self.writer.submit(lambda c: c.execute("INSERT OR IGNORE INTO incident_events(incident_id,timestamp,event_type,payload_json,dedupe_key) VALUES(?,?,?,?,?)", (incident_id,ts,event_type,body,dedupe_key)))
    def add_prediction(self, incident_id: str, label: str, confidence: float, model_id: str | None, payload: dict[str, Any] | None = None, assurance_level: str = "FULL") -> bool:
        return self.writer.submit(lambda c: c.execute("INSERT INTO predictions(incident_id,timestamp,label,confidence,model_id,payload_json,assurance_level) VALUES(?,?,?,?,?,?,?)", (incident_id,utc_now(),label,confidence,model_id,json.dumps(payload or {},sort_keys=True),assurance_level)))
    def add_operator_action(self, incident_id: str, operator_id: str, action: str, approved: bool, payload: dict[str, Any] | None = None) -> bool:
        return self.writer.submit(lambda c: c.execute("INSERT INTO operator_actions(incident_id,timestamp,operator_id,action,approved,payload_json) VALUES(?,?,?,?,?,?)", (incident_id,utc_now(),operator_id,action,int(approved),json.dumps(payload or {},sort_keys=True))))
    def add_note(self, incident_id: str, operator_id: str, operator_role: str, note: str) -> bool:
        return self.writer.submit(lambda c: c.execute("INSERT INTO incident_notes(incident_id,timestamp,operator_id,operator_role,note) VALUES(?,?,?,?,?)", (incident_id,utc_now(),operator_id,operator_role,note)))
    def add_feedback(self, prediction_id: int, label: str, corrected_class: str | None, operator_id: str, operator_role: str, comment: str | None) -> bool:
        return self.writer.submit(lambda c: c.execute("INSERT INTO prediction_feedback(prediction_id,label,corrected_class,operator_id,operator_role,timestamp,comment) VALUES(?,?,?,?,?,?,?)", (prediction_id,label,corrected_class,operator_id,operator_role,utc_now(),comment)))
    def add_assurance_state(self, incident_id: str, model_id: str | None, state: str, payload: dict[str, Any] | None = None) -> bool:
        return self.writer.submit(lambda c: c.execute("INSERT INTO assurance_states(incident_id,timestamp,model_id,state,payload_json) VALUES(?,?,?,?,?)", (incident_id,utc_now(),model_id,state,json.dumps(payload or {},sort_keys=True))))
    def attach_evidence(self, incident_id: str, kind: str, source: Path) -> bool:
        source = Path(source); digest = sha256(source.read_bytes()).hexdigest()
        return self.writer.submit(lambda c: c.execute("INSERT INTO evidence(incident_id,timestamp,kind,source_path,sha256) VALUES(?,?,?,?,?)", (incident_id,utc_now(),kind,str(source),digest)))
    def update_incident_risk(self, incident_id: str, level: str, breakdown: dict[str, Any]) -> bool:
        return self.writer.submit(lambda c: c.execute("UPDATE incidents SET risk_level=?, risk_breakdown_json=?, updated_at=? WHERE incident_id=?", (level,json.dumps(breakdown,sort_keys=True),utc_now(),incident_id)))
    def close_incident(self, incident_id: str, outcome: str) -> bool:
        return self.writer.submit(lambda c: c.execute("UPDATE incidents SET status=?, outcome=?, updated_at=? WHERE incident_id=?", (IncidentStatus.CLOSED.value,outcome,utc_now(),incident_id)))
    def rows(self, table: str, incident_id: str | None = None) -> list[dict[str, Any]]:
        allowed = {"incidents","incident_events","predictions","operator_actions","evidence","assurance_states","incident_notes","device_health_events","sync_outbox","drift_snapshots","model_baselines"}
        if table not in allowed: raise ValueError("invalid table")
        if incident_id is None:
            return [dict(r) for r in self._read(f"SELECT * FROM {table} ORDER BY id DESC")]
        key = "incident_id"; return [dict(r) for r in self._read(f"SELECT * FROM {table} WHERE {key}=? ORDER BY id" if table != "incidents" else "SELECT * FROM incidents WHERE incident_id=?", (incident_id,))]
    def close(self) -> None: self.writer.close()


class EvidenceExporter:
    def __init__(self, repository: IncidentRepository, root: Path): self.repository, self.root = repository, Path(root)
    def export(self, incident_id: str, zip_package: bool = True) -> Path:
        self.repository.writer.drain(); target = self.root / incident_id; files = target / "files"; files.mkdir(parents=True, exist_ok=True)
        evidence = self.repository.rows("evidence", incident_id); packaged = []
        for item in evidence:
            source = Path(item["source_path"])
            if source.exists():
                destination = files / source.name; shutil.copy2(source, destination)
                packaged.append({"kind": item["kind"], "file": str(destination.relative_to(target)), "sha256": sha256(destination.read_bytes()).hexdigest()})
        manifest = {"incident": self.repository.rows("incidents",incident_id)[0], "timeline": self.repository.rows("incident_events",incident_id), "predictions": self.repository.rows("predictions",incident_id), "operator_actions": self.repository.rows("operator_actions",incident_id), "evidence": packaged}
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        if zip_package: shutil.make_archive(str(target), "zip", target)
        return target / "manifest.json"
    @staticmethod
    def verify(manifest_path: Path) -> bool:
        manifest_path = Path(manifest_path); manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in manifest["evidence"]:
            file_path = manifest_path.parent / item["file"]
            if not file_path.exists() or sha256(file_path.read_bytes()).hexdigest() != item["sha256"]: return False
        return True


class ModelRegistry:
    def __init__(self, repository: IncidentRepository): self.repository = repository
    def register(self, model_id: str, name: str, version: str, model_path: Path | None, held_out_f1: str = "UNVERIFIED", readiness: str = "UNVERIFIED") -> None:
        digest = sha256(Path(model_path).read_bytes()).hexdigest() if model_path and Path(model_path).exists() else None
        c = self.repository.config
        self.repository.writer.submit(lambda db: db.execute("INSERT OR REPLACE INTO models VALUES(?,?,?,?,?,?,?,?,?)", (model_id,name,version,digest,held_out_f1,readiness,c.usage_restriction,"READY",utc_now())))
    def verify_on_startup(self, model_id: str, model_path: Path) -> bool:
        self.repository.writer.drain(); rows = self.repository._read("SELECT sha256 FROM models WHERE model_id=?", (model_id,))
        actual = sha256(Path(model_path).read_bytes()).hexdigest() if Path(model_path).exists() else None
        expected = rows[0]["sha256"] if rows else None; ok = bool(expected and expected == actual)
        status = "READY" if ok else IncidentStatus.REVIEW_REQUIRED.value
        self.repository.writer.submit(lambda db: (db.execute("UPDATE models SET status=? WHERE model_id=?", (status,model_id)), db.execute("INSERT INTO deployments(model_id,timestamp,event,status,details_json) VALUES(?,?,?,?,?)", (model_id,utc_now(),"startup_checksum",status,json.dumps({"expected":expected,"actual":actual})))))
        return ok
    def populate_from_assurance(self) -> list[str]:
        """Register existing assurance outputs without fabricating unavailable metrics."""
        from src.modules.assurance.model_assurance import MODEL_ASSURANCE
        summary = MODEL_ASSURANCE.summarize({})
        created: list[str] = []
        for item in summary.get("modalities", []):
            modality = str(item["modality"])
            model_id = f"assurance-{modality}"
            f1 = item.get("held_out_f1")
            self.register(
                model_id, modality, str(summary.get("profile", "legacy")), None,
                str(f1) if isinstance(f1, (int, float)) else "UNVERIFIED",
                str(item.get("readiness") or "UNVERIFIED"),
            )
            created.append(model_id)
        return created
