"""
Database Backup and Disaster Recovery for Sentinel-AI Edge Appliance.
Uses SQLite's non-blocking Online Backup API with SHA-256 checksum verification,
metadata manifests, and post-restore cryptographic/schema integrity auditing.
"""

from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable, Dict, Optional

from src.modules.core.version import SCHEMA_VERSION


class BackupError(Exception):
    """Base error for backup/restore operations."""
    pass


class BackupIntegrityError(BackupError):
    """Raised when backup file checksum or SQLite integrity checks fail."""
    pass


def _sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def create_online_backup(
    source_db_path: Path | str,
    target_backup_path: Path | str,
    pages_per_step: int = 100,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """
    Creates an atomic, consistent online backup of source SQLite DB without locking writers.
    Generates a companion metadata manifest (.meta.json) with SHA-256 digest.
    """
    src_p = Path(source_db_path)
    tgt_p = Path(target_backup_path)

    if not src_p.is_file():
        raise BackupError(f"Source database file not found: {src_p}")

    tgt_p.parent.mkdir(parents=True, exist_ok=True)
    if tgt_p.exists():
        tgt_p.unlink()

    meta_p = tgt_p.with_suffix(tgt_p.suffix + ".meta.json")
    if meta_p.exists():
        meta_p.unlink()

    start_time = time.monotonic()
    timestamp_utc = datetime.now(timezone.utc).isoformat()

    # Perform online backup
    src_conn = sqlite3.connect(f"file:{src_p.resolve()}?mode=ro", uri=True)
    tgt_conn = sqlite3.connect(str(tgt_p))

    try:
        with tgt_conn:
            src_conn.backup(tgt_conn, pages=pages_per_step, progress=progress_callback)
    finally:
        tgt_conn.close()
        src_conn.close()

    elapsed = round(time.monotonic() - start_time, 3)
    file_size = tgt_p.stat().st_size
    checksum = _sha256_file(tgt_p)

    metadata = {
        "source_db": str(src_p),
        "target_backup": str(tgt_p),
        "timestamp_utc": timestamp_utc,
        "elapsed_seconds": elapsed,
        "size_bytes": file_size,
        "sha256": checksum,
        "schema_version": SCHEMA_VERSION,
        "pages_per_step": pages_per_step,
    }

    meta_p.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def verify_database_integrity(db_path: Path | str) -> Dict[str, Any]:
    """
    Runs comprehensive SQLite PRAGMA checks and table verification.
    """
    p = Path(db_path)
    if not p.is_file():
        raise BackupError(f"Database file not found: {p}")

    con = sqlite3.connect(str(p), timeout=5.0)
    con.row_factory = sqlite3.Row
    try:
        # PRAGMA integrity_check
        res = con.execute("PRAGMA integrity_check").fetchall()
        integrity_ok = len(res) == 1 and res[0][0] == "ok"
        integrity_errors = [r[0] for r in res] if not integrity_ok else []

        # PRAGMA quick_check
        qres = con.execute("PRAGMA quick_check").fetchall()
        quick_ok = len(qres) == 1 and qres[0][0] == "ok"

        # Foreign keys check
        fk_res = con.execute("PRAGMA foreign_key_check").fetchall()
        fk_errors = [dict(r) for r in fk_res]

        # Table statistics
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        table_counts = {}
        for t in tables:
            try:
                cnt = con.execute(f"SELECT COUNT(*) FROM \"{t}\"").fetchone()[0]
                table_counts[t] = cnt
            except Exception:
                pass

        status = "PASSED" if (integrity_ok and quick_ok and len(fk_errors) == 0) else "FAILED"
        return {
            "status": status,
            "db_path": str(p),
            "integrity_ok": integrity_ok,
            "integrity_errors": integrity_errors,
            "quick_check_ok": quick_ok,
            "foreign_key_violations": fk_errors,
            "tables_found": tables,
            "table_counts": table_counts,
        }
    finally:
        con.close()


def restore_backup(
    backup_path: Path | str,
    target_db_path: Path | str,
    verify_checksum: bool = True,
) -> Dict[str, Any]:
    """
    Restores a database from an online backup snapshot, verifies cryptographic checksum
    and runs full SQLite integrity check on the destination database.
    """
    b_path = Path(backup_path)
    t_path = Path(target_db_path)

    if not b_path.is_file():
        raise BackupError(f"Backup file not found: {b_path}")

    # Checksum validation if manifest exists
    meta_path = b_path.with_suffix(b_path.suffix + ".meta.json")
    if meta_path.is_file() and verify_checksum:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            expected_hash = meta.get("sha256")
            if expected_hash:
                actual_hash = _sha256_file(b_path)
                if actual_hash != expected_hash:
                    raise BackupIntegrityError(
                        f"Checksum mismatch for backup file {b_path}!\n"
                        f"Expected SHA-256: {expected_hash}\n"
                        f"Actual SHA-256:   {actual_hash}"
                    )
        except json.JSONDecodeError:
            pass

    t_path.parent.mkdir(parents=True, exist_ok=True)

    # Perform online restore from backup file to target file
    start_time = time.monotonic()
    b_conn = sqlite3.connect(f"file:{b_path.resolve()}?mode=ro", uri=True)
    t_conn = sqlite3.connect(str(t_path))

    try:
        with t_conn:
            b_conn.backup(t_conn, pages=100)
    finally:
        t_conn.close()
        b_conn.close()

    elapsed = round(time.monotonic() - start_time, 3)

    # Verify restored database
    verification = verify_database_integrity(t_path)
    if verification["status"] != "PASSED":
        raise BackupIntegrityError(
            f"Restored database failed integrity check: {verification.get('integrity_errors')}"
        )

    return {
        "status": "RESTORED_AND_VERIFIED",
        "backup_path": str(b_path),
        "target_db_path": str(t_path),
        "elapsed_seconds": elapsed,
        "verification": verification,
    }
