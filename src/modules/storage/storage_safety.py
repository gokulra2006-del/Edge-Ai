"""Production data retention, storage safety, WAL checkpointing, and safe cleanup."""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Dict, List, Optional, Tuple

from src.config.governance_config import load_governance_config
from src.modules.database.governed_store import IncidentRepository, utc_now
from src.modules.logging.logger import LOGGER

ROOT_DIR = Path(__file__).resolve().parents[3]


def parse_iso_timestamp(ts_str: str) -> datetime:
    """Safely parse ISO timestamp into timezone-aware datetime."""
    try:
        # Replace Z with +00:00 if present
        clean_str = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


class WalCheckpointManager:
    """
    Manages SQLite Write-Ahead Log (WAL) checkpoints and auto-truncation.
    Supports PASSIVE, FULL, RESTART, and TRUNCATE checkpointing modes.
    """

    def __init__(self, db_path: Path, auto_truncate_bytes: int = 10485760):
        self.db_path = Path(db_path)
        self.wal_path = Path(str(self.db_path) + "-wal")
        self.auto_truncate_bytes = auto_truncate_bytes

    def get_wal_size(self) -> int:
        """Returns the current size of the WAL file in bytes."""
        if self.wal_path.exists():
            try:
                return self.wal_path.stat().st_size
            except Exception:
                return 0
        return 0

    def checkpoint(self, mode: str = "PASSIVE") -> Dict[str, Any]:
        """
        Executes a WAL checkpoint against the SQLite database.
        Modes: PASSIVE (0), FULL (1), RESTART (2), TRUNCATE (3).
        """
        mode_upper = mode.upper()
        if mode_upper not in ("PASSIVE", "FULL", "RESTART", "TRUNCATE"):
            raise ValueError(f"Invalid WAL checkpoint mode: {mode}")

        size_before = self.get_wal_size()
        busy = 0
        log_pages = 0
        checkpointed_pages = 0

        try:
            with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute(f"PRAGMA wal_checkpoint({mode_upper});")
                row = cursor.fetchone()
                if row:
                    busy, log_pages, checkpointed_pages = row[0], row[1], row[2]
        except Exception as e:
            LOGGER.error(f"WAL checkpoint error ({mode_upper}): {e}")
            return {
                "success": False,
                "mode": mode_upper,
                "error": str(e),
                "wal_size_before": size_before,
                "wal_size_after": self.get_wal_size(),
            }

        size_after = self.get_wal_size()
        return {
            "success": True,
            "mode": mode_upper,
            "busy": bool(busy),
            "log_pages": log_pages,
            "checkpointed_pages": checkpointed_pages,
            "wal_size_before": size_before,
            "wal_size_after": size_after,
            "bytes_reclaimed": max(0, size_before - size_after),
        }

    def auto_manage(self) -> Optional[Dict[str, Any]]:
        """
        Inspects WAL size and automatically triggers a TRUNCATE checkpoint
        if the WAL exceeds the auto_truncate_bytes threshold.
        """
        current_size = self.get_wal_size()
        if current_size >= self.auto_truncate_bytes:
            LOGGER.info(
                f"WAL size ({current_size} bytes) exceeds auto-truncate threshold "
                f"({self.auto_truncate_bytes} bytes). Executing TRUNCATE checkpoint."
            )
            return self.checkpoint(mode="TRUNCATE")
        return None


class StorageRetentionEngine:
    """
    Production storage safety engine that enforces retention policies,
    compresses/archives telemetry, evicts old DVR recordings, and safeguards critical data.
    """

    def __init__(
        self,
        repository: IncidentRepository,
        config: Optional[Dict[str, Any]] = None,
        base_dir: Optional[Path] = None,
    ):
        self.repository = repository
        self.base_dir = base_dir or ROOT_DIR
        self.config = config or self._load_config()

        # Storage retention configuration
        storage_cfg = self.config.get("storage", {})
        ret_cfg = storage_cfg.get("retention", {})
        thresh_cfg = storage_cfg.get("thresholds", {})
        paths_cfg = storage_cfg.get("paths", {})
        wal_cfg = storage_cfg.get("wal", {})

        self.raw_telemetry_days = int(ret_cfg.get("raw_telemetry_days", 7))
        self.archive_telemetry_after_days = int(ret_cfg.get("archive_telemetry_after_days", 3))
        self.dvr_max_bytes = int(ret_cfg.get("dvr_max_bytes", 524288000))  # 500 MB
        self.evidence_retention_days = int(ret_cfg.get("evidence_retention_days", 30))
        self.reports_retention_days = int(ret_cfg.get("reports_retention_days", 90))
        self.logs_retention_days = int(ret_cfg.get("logs_retention_days", 14))
        self.synced_outbox_retention_days = int(ret_cfg.get("synced_outbox_retention_days", 7))

        self.warning_bytes = int(thresh_cfg.get("warning_bytes", 1000000000))
        self.critical_bytes = int(thresh_cfg.get("critical_bytes", 250000000))

        # Paths
        self.archives_dir = self._resolve_path(paths_cfg.get("archives_dir", "data/archives"))
        self.dvr_dir = self._resolve_path(paths_cfg.get("dvr_dir", "data/recordings"))
        self.evidence_dir = self._resolve_path(paths_cfg.get("evidence_dir", "data/evidence"))
        self.reports_dir = self._resolve_path(paths_cfg.get("reports_dir", "reports"))
        self.logs_dir = self._resolve_path(paths_cfg.get("logs_dir", "logs"))

        # WAL Manager
        auto_trunc = int(wal_cfg.get("auto_truncate_bytes", 10485760))
        self.wal_manager = WalCheckpointManager(self.repository.db_path, auto_truncate_bytes=auto_trunc)

    def _resolve_path(self, rel_or_abs: str) -> Path:
        p = Path(rel_or_abs)
        if p.is_absolute():
            return p
        return self.base_dir / p

    def _load_config(self) -> Dict[str, Any]:
        cfg_file = self.base_dir / "src" / "config" / "advanced_platform.json"
        try:
            return json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def log_cleanup_action(
        self,
        policy_type: str,
        items_inspected: int,
        items_archived: int,
        items_pruned: int,
        bytes_freed: int,
        dry_run: bool,
        details: Dict[str, Any],
    ) -> None:
        """Records an immutable cleanup record in the storage_cleanup_logs ledger."""
        now = utc_now()
        det_json = json.dumps(details, sort_keys=True)
        try:
            with sqlite3.connect(str(self.repository.db_path), timeout=5.0) as conn:
                conn.execute(
                    """
                    INSERT INTO storage_cleanup_logs
                    (timestamp, policy_type, items_inspected, items_archived, items_pruned, bytes_freed, dry_run, details_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (now, policy_type, items_inspected, items_archived, items_pruned, bytes_freed, 1 if dry_run else 0, det_json),
                )
        except Exception as e:
            LOGGER.error(f"Failed to log storage cleanup record: {e}")

    # -------------------------------------------------------------------------
    # 1. Telemetry Archival & Pruning
    # -------------------------------------------------------------------------
    def archive_telemetry(
        self, dry_run: bool = False, older_than_days: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Compresses telemetry rows older than threshold into a gzip JSON archive,
        verifies the archive integrity, then safely prunes raw rows from SQLite.
        """
        days = older_than_days if older_than_days is not None else self.archive_telemetry_after_days
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_ts = cutoff_dt.isoformat()

        # Check telemetry_logs table
        rows_to_archive: List[Dict[str, Any]] = []
        try:
            with sqlite3.connect(str(self.repository.db_path), timeout=5.0) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='telemetry_logs'"
                )
                if cursor.fetchone():
                    cursor.execute(
                        "SELECT * FROM telemetry_logs WHERE timestamp < ? ORDER BY id ASC",
                        (cutoff_ts,),
                    )
                    rows_to_archive = [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            LOGGER.error(f"Error querying telemetry logs: {e}")

        total_rows = len(rows_to_archive)
        result = {
            "policy": "telemetry",
            "dry_run": dry_run,
            "cutoff_timestamp": cutoff_ts,
            "items_inspected": total_rows,
            "items_archived": 0,
            "items_pruned": 0,
            "bytes_freed": 0,
            "archive_file": None,
        }

        if total_rows == 0:
            self.log_cleanup_action("telemetry", 0, 0, 0, 0, dry_run, result)
            return result

        if dry_run:
            # Estimate raw bytes
            sample_bytes = sum(len(json.dumps(r)) for r in rows_to_archive)
            result["items_archived"] = total_rows
            result["items_pruned"] = total_rows
            result["bytes_freed"] = sample_bytes
            self.log_cleanup_action("telemetry", total_rows, total_rows, total_rows, sample_bytes, dry_run, result)
            return result

        # Real Execution: Export & Compress
        self.archives_dir.mkdir(parents=True, exist_ok=True)
        ts_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_name = f"telemetry_archive_{ts_tag}.json.gz"
        archive_path = self.archives_dir / archive_name

        payload = {
            "archived_at": utc_now(),
            "cutoff": cutoff_ts,
            "row_count": total_rows,
            "rows": rows_to_archive,
        }
        json_bytes = json.dumps(payload, indent=2).encode("utf-8")
        uncompressed_size = len(json_bytes)

        with gzip.open(archive_path, "wb") as gz:
            gz.write(json_bytes)

        # Verify archive
        if not archive_path.exists() or archive_path.stat().st_size == 0:
            raise RuntimeError(f"Archive file creation failed or is empty: {archive_path}")

        archive_sha = sha256(archive_path.read_bytes()).hexdigest()
        archive_size = archive_path.stat().st_size

        # Prune raw rows from table
        max_id = max(r["id"] for r in rows_to_archive)
        with sqlite3.connect(str(self.repository.db_path), timeout=5.0) as conn:
            conn.execute(
                "DELETE FROM telemetry_logs WHERE timestamp < ? AND id <= ?",
                (cutoff_ts, max_id),
            )

        bytes_reclaimed = max(0, uncompressed_size - archive_size)
        result["items_archived"] = total_rows
        result["items_pruned"] = total_rows
        result["bytes_freed"] = bytes_reclaimed
        result["archive_file"] = str(archive_path)
        result["archive_sha256"] = archive_sha
        result["archive_size_bytes"] = archive_size

        self.log_cleanup_action(
            "telemetry", total_rows, total_rows, total_rows, bytes_reclaimed, dry_run, result
        )
        return result

    # -------------------------------------------------------------------------
    # 2. DVR Oldest-First Eviction
    # -------------------------------------------------------------------------
    def evict_dvr(
        self, dry_run: bool = False, max_bytes: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Enforces the DVR storage cap on recordings.
        Evicts oldest recordings first until total bytes is within the cap.
        """
        cap = max_bytes if max_bytes is not None else self.dvr_max_bytes
        self.dvr_dir.mkdir(parents=True, exist_ok=True)

        # Scan recordings
        files = []
        total_size = 0
        for p in self.dvr_dir.iterdir():
            if p.is_file() and not p.name.startswith("."):
                sz = p.stat().st_size
                mtime = p.stat().st_mtime
                files.append((mtime, sz, p))
                total_size += sz

        # Sort oldest first
        files.sort(key=lambda x: x[0])

        bytes_to_evict = max(0, total_size - cap)
        evicted_files = []
        freed_bytes = 0

        current_bytes = total_size
        for mtime, sz, path in files:
            if current_bytes <= cap:
                break
            evicted_files.append({"path": str(path), "size_bytes": sz, "mtime": mtime})
            freed_bytes += sz
            current_bytes -= sz
            if not dry_run:
                try:
                    path.unlink()
                except Exception as e:
                    LOGGER.error(f"Failed to unlink DVR recording {path}: {e}")

        result = {
            "policy": "dvr",
            "dry_run": dry_run,
            "dvr_cap_bytes": cap,
            "total_size_before": total_size,
            "total_size_after": total_size - freed_bytes,
            "items_inspected": len(files),
            "items_archived": 0,
            "items_pruned": len(evicted_files),
            "bytes_freed": freed_bytes,
            "evicted_files": [f["path"] for f in evicted_files],
        }

        self.log_cleanup_action("dvr", len(files), 0, len(evicted_files), freed_bytes, dry_run, result)
        return result

    # -------------------------------------------------------------------------
    # 3. Safe Evidence Cleanup
    # -------------------------------------------------------------------------
    def cleanup_evidence(
        self, dry_run: bool = False, retention_days: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Prunes obsolete evidence files with strict safety guarantees:
        - NEVER deletes evidence linked to active/unresolved incidents.
        - NEVER deletes evidence linked to recent incidents (within retention_days).
        - NEVER deletes audit records.
        """
        days = retention_days if retention_days is not None else self.evidence_retention_days
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_ts = cutoff_dt.isoformat()

        # Query all evidence with incident status and creation time
        safe_to_delete: List[Dict[str, Any]] = []
        protected_count = 0
        inspected_count = 0

        try:
            with sqlite3.connect(str(self.repository.db_path), timeout=5.0) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT e.id, e.incident_id, e.source_path, e.sha256, e.timestamp,
                           i.status as incident_status, i.created_at as incident_created_at
                    FROM evidence e
                    LEFT JOIN incidents i ON e.incident_id = i.incident_id
                    """
                )
                rows = cursor.fetchall()
                inspected_count = len(rows)

                for r in rows:
                    inc_status = r["incident_status"]
                    inc_created = r["incident_created_at"] or r["timestamp"]

                    # Protection rule:
                    # If incident is active/unresolved (OPEN, ACKNOWLEDGED, CONFIRMED, ESCALATED, REVIEW_REQUIRED)
                    # OR incident was created after cutoff -> PROTECTED
                    is_active = inc_status not in ("CLOSED", "RESOLVED", "FALSE_ALARM")
                    is_recent = inc_created >= cutoff_ts

                    if is_active or is_recent:
                        protected_count += 1
                    else:
                        safe_to_delete.append(dict(r))
        except Exception as e:
            LOGGER.error(f"Error checking evidence retention: {e}")

        freed_bytes = 0
        pruned_count = 0
        pruned_ids = []

        for item in safe_to_delete:
            p = Path(item["source_path"])
            sz = 0
            if p.exists() and p.is_file():
                sz = p.stat().st_size
                if not dry_run:
                    try:
                        p.unlink()
                    except Exception as e:
                        LOGGER.error(f"Failed to delete evidence file {p}: {e}")
            freed_bytes += sz
            pruned_count += 1
            pruned_ids.append(item["id"])

        if not dry_run and pruned_ids:
            try:
                with sqlite3.connect(str(self.repository.db_path), timeout=5.0) as conn:
                    # Placeholders
                    placeholders = ",".join("?" for _ in pruned_ids)
                    conn.execute(f"DELETE FROM evidence WHERE id IN ({placeholders})", pruned_ids)
            except Exception as e:
                LOGGER.error(f"Failed to delete evidence records: {e}")

        result = {
            "policy": "evidence",
            "dry_run": dry_run,
            "retention_days": days,
            "cutoff_timestamp": cutoff_ts,
            "items_inspected": inspected_count,
            "items_protected": protected_count,
            "items_archived": 0,
            "items_pruned": pruned_count,
            "bytes_freed": freed_bytes,
        }

        self.log_cleanup_action("evidence", inspected_count, 0, pruned_count, freed_bytes, dry_run, result)
        return result

    # -------------------------------------------------------------------------
    # 4. Reports and Logs Cleanup
    # -------------------------------------------------------------------------
    def cleanup_reports(
        self, dry_run: bool = False, retention_days: Optional[int] = None
    ) -> Dict[str, Any]:
        """Prunes generated HTML/PDF/CSV reports older than retention policy."""
        days = retention_days if retention_days is not None else self.reports_retention_days
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_ts = cutoff_dt.timestamp()

        self.reports_dir.mkdir(parents=True, exist_ok=True)
        inspected = 0
        pruned = 0
        freed = 0

        for p in self.reports_dir.iterdir():
            if p.is_file() and p.name not in (".gitkeep", "manifest.json"):
                inspected += 1
                if p.stat().st_mtime < cutoff_ts:
                    sz = p.stat().st_size
                    freed += sz
                    pruned += 1
                    if not dry_run:
                        try:
                            p.unlink()
                        except Exception:
                            pass

        result = {
            "policy": "reports",
            "dry_run": dry_run,
            "items_inspected": inspected,
            "items_archived": 0,
            "items_pruned": pruned,
            "bytes_freed": freed,
        }
        self.log_cleanup_action("reports", inspected, 0, pruned, freed, dry_run, result)
        return result

    def cleanup_logs(
        self, dry_run: bool = False, retention_days: Optional[int] = None
    ) -> Dict[str, Any]:
        """Prunes log files older than retention policy."""
        days = retention_days if retention_days is not None else self.logs_retention_days
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_ts = cutoff_dt.timestamp()

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        inspected = 0
        pruned = 0
        freed = 0

        for p in self.logs_dir.iterdir():
            if p.is_file() and not p.name.startswith("."):
                inspected += 1
                if p.stat().st_mtime < cutoff_ts:
                    sz = p.stat().st_size
                    freed += sz
                    pruned += 1
                    if not dry_run:
                        try:
                            p.unlink()
                        except Exception:
                            pass

        result = {
            "policy": "logs",
            "dry_run": dry_run,
            "items_inspected": inspected,
            "items_archived": 0,
            "items_pruned": pruned,
            "bytes_freed": freed,
        }
        self.log_cleanup_action("logs", inspected, 0, pruned, freed, dry_run, result)
        return result

    # -------------------------------------------------------------------------
    # 5. Outbox Cleanup (Protected Unsynced Safeguard)
    # -------------------------------------------------------------------------
    def cleanup_outbox(
        self, dry_run: bool = False, retention_days: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Safely cleans SYNCED outbox records older than retention threshold.
        NEVER deletes PENDING or DEAD_LETTER items!
        """
        days = retention_days if retention_days is not None else self.synced_outbox_retention_days
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_ts = cutoff_dt.isoformat()

        inspected = 0
        pruned = 0
        try:
            with sqlite3.connect(str(self.repository.db_path), timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT count(*) FROM sync_outbox")
                inspected = cursor.fetchone()[0]

                cursor.execute(
                    "SELECT count(*) FROM sync_outbox WHERE status='SYNCED' AND updated_at < ?",
                    (cutoff_ts,),
                )
                pruned = cursor.fetchone()[0]

                if not dry_run and pruned > 0:
                    cursor.execute(
                        "DELETE FROM sync_outbox WHERE status='SYNCED' AND updated_at < ?",
                        (cutoff_ts,),
                    )
                    conn.commit()
        except Exception as e:
            LOGGER.error(f"Error cleaning sync outbox: {e}")

        result = {
            "policy": "outbox",
            "dry_run": dry_run,
            "items_inspected": inspected,
            "items_archived": 0,
            "items_pruned": pruned,
            "bytes_freed": pruned * 512,  # estimated row bytes
        }
        self.log_cleanup_action("outbox", inspected, 0, pruned, result["bytes_freed"], dry_run, result)
        return result

    # -------------------------------------------------------------------------
    # 6. Full Cleanup Orchestrator & Storage Health Status
    # -------------------------------------------------------------------------
    def run_full_cleanup(self, dry_run: bool = False) -> Dict[str, Any]:
        """Executes all storage cleanup policies safely in order, returning summary manifest."""
        res_telem = self.archive_telemetry(dry_run=dry_run)
        res_dvr = self.evict_dvr(dry_run=dry_run)
        res_evid = self.cleanup_evidence(dry_run=dry_run)
        res_rep = self.cleanup_reports(dry_run=dry_run)
        res_logs = self.cleanup_logs(dry_run=dry_run)
        res_outbox = self.cleanup_outbox(dry_run=dry_run)

        # Checkpoint WAL if not dry-run
        wal_res = None
        if not dry_run:
            wal_res = self.wal_manager.auto_manage()

        total_freed = (
            res_telem["bytes_freed"]
            + res_dvr["bytes_freed"]
            + res_evid["bytes_freed"]
            + res_rep["bytes_freed"]
            + res_logs["bytes_freed"]
            + res_outbox["bytes_freed"]
            + (wal_res.get("bytes_reclaimed", 0) if wal_res else 0)
        )
        total_pruned = (
            res_telem["items_pruned"]
            + res_dvr["items_pruned"]
            + res_evid["items_pruned"]
            + res_rep["items_pruned"]
            + res_logs["items_pruned"]
            + res_outbox["items_pruned"]
        )

        manifest = {
            "timestamp": utc_now(),
            "dry_run": dry_run,
            "total_items_pruned": total_pruned,
            "total_bytes_freed": total_freed,
            "subsystems": {
                "telemetry": res_telem,
                "dvr": res_dvr,
                "evidence": res_evid,
                "reports": res_rep,
                "logs": res_logs,
                "outbox": res_outbox,
                "wal_checkpoint": wal_res,
            },
        }

        self.log_cleanup_action(
            "full_system",
            res_telem["items_inspected"] + res_dvr["items_inspected"] + res_evid["items_inspected"],
            res_telem["items_archived"],
            total_pruned,
            total_freed,
            dry_run,
            manifest,
        )
        return manifest


class StorageSafetyStatus:
    """Provides high-level system storage metrics and threshold evaluation for dashboards and alerts."""

    def __init__(self, engine: StorageRetentionEngine):
        self.engine = engine

    def _dir_size(self, path: Path) -> int:
        if not path.exists():
            return 0
        total = 0
        try:
            for root, _, files in os.walk(path):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except Exception:
                        pass
        except Exception:
            pass
        return total

    def get_status(self) -> Dict[str, Any]:
        """Computes live storage utilization against warning and critical thresholds."""
        db_parent = self.engine.repository.db_path.parent
        usage = shutil.disk_usage(db_parent)
        free_bytes = usage.free
        total_bytes = usage.total
        used_bytes = usage.used

        # Evaluate threshold status
        if free_bytes < self.engine.critical_bytes:
            status = "DOWN"
            reason = "STORAGE_CRITICAL"
            msg = f"Storage critically low: {free_bytes // (1024 * 1024)} MB available"
        elif free_bytes < self.engine.warning_bytes:
            status = "DEGRADED"
            reason = "STORAGE_WARNING"
            msg = f"Storage low: {free_bytes // (1024 * 1024)} MB available"
        else:
            status = "OK"
            reason = "NOMINAL"
            msg = f"Storage healthy: {free_bytes // (1024 * 1024 * 1024)} GB available"

        dvr_size = self._dir_size(self.engine.dvr_dir)
        archives_size = self._dir_size(self.engine.archives_dir)
        evidence_size = self._dir_size(self.engine.evidence_dir)
        reports_size = self._dir_size(self.engine.reports_dir)
        logs_size = self._dir_size(self.engine.logs_dir)
        wal_size = self.engine.wal_manager.get_wal_size()
        db_size = self.engine.repository.db_path.stat().st_size if self.engine.repository.db_path.exists() else 0

        # Query recent cleanup log
        last_cleanup = None
        try:
            with sqlite3.connect(str(self.engine.repository.db_path), timeout=2.0) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT timestamp, policy_type, items_pruned, bytes_freed, dry_run FROM storage_cleanup_logs ORDER BY id DESC LIMIT 1"
                )
                r = cursor.fetchone()
                if r:
                    last_cleanup = dict(r)
        except Exception:
            pass

        return {
            "status": status,
            "reason_code": reason,
            "message": msg,
            "free_bytes": free_bytes,
            "total_bytes": total_bytes,
            "used_bytes": used_bytes,
            "free_percent": round((free_bytes / total_bytes) * 100, 1) if total_bytes > 0 else 0,
            "thresholds": {
                "warning_bytes": self.engine.warning_bytes,
                "critical_bytes": self.engine.critical_bytes,
                "dvr_max_bytes": self.engine.dvr_max_bytes,
            },
            "subsystem_bytes": {
                "database": db_size,
                "wal": wal_size,
                "dvr": dvr_size,
                "archives": archives_size,
                "evidence": evidence_size,
                "reports": reports_size,
                "logs": logs_size,
            },
            "last_cleanup": last_cleanup,
        }
