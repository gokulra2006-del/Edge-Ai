#!/usr/bin/env python3
"""
scripts/storage/migrate_evidence_encryption.py
Migration CLI for existing unencrypted evidence files at rest (Phase 6K).

Scans evidence directory and database records:
1. Detects unencrypted files (files lacking SEN_EVID_V1 magic container header).
2. Computes plaintext SHA-256 hash.
3. Encrypts with active AES-256-GCM key from KeyRing.
4. Atomically replaces plaintext with authenticated envelope container (.enc).
5. Updates SQLite evidence table (encrypted=1, key_id, encryption_algo='AES-256-GCM').
6. Verifies that the stored plaintext hash is preserved bit-for-bit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional, Tuple, Union

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.modules.database.governed_store import IncidentRepository, utc_now
from src.modules.storage.evidence_encryption import (
    EvidenceEncryptor,
    EvidenceKeyRing,
    MAGIC_HEADER,
)


def migrate_evidence_directory(
    directory: Union[str, Path],
    encryptor: Optional[EvidenceEncryptor] = None,
    incident_id: str = "INC-UNKNOWN",
    delete_unencrypted: bool = True,
) -> Dict[str, Any]:
    """
    Convenience function to batch-encrypt all unencrypted files in a directory.
    """
    dir_p = Path(directory)
    enc = encryptor or EvidenceEncryptor()
    encrypted_count = 0
    failed_count = 0
    total_bytes = 0

    for root, _, files in os.walk(dir_p):
        for f in files:
            p = Path(root) / f
            if p.suffix in (".tmp", ".reenc"):
                continue
            if enc.is_encrypted_file(p):
                continue
            try:
                enc_p, _ = enc.encrypt_file(
                    source_path=p,
                    dest_path=p.with_name(p.name + ".enc") if not p.name.endswith(".enc") else p,
                    incident_id=incident_id,
                )
                total_bytes += enc_p.stat().st_size
                encrypted_count += 1
                if delete_unencrypted and enc_p != p and p.exists():
                    p.unlink()
            except Exception:
                failed_count += 1

    return {
        "status": "COMPLETED",
        "encrypted_count": encrypted_count,
        "failed_count": failed_count,
        "total_bytes": total_bytes,
    }


def migrate_unencrypted_evidence(
    evidence_dir: Union[str, Path] = REPO_ROOT / "data" / "evidence",
    db_path: Optional[Union[str, Path]] = None,
    key_ring: Optional[EvidenceKeyRing] = None,
    dry_run: bool = False,
    operator_id: str = "migration_admin",
    replace_plaintext: bool = True,
) -> Dict[str, Any]:
    start_ts = time.monotonic()
    ev_dir = Path(evidence_dir)

    ev_dir.mkdir(parents=True, exist_ok=True)

    target_db = Path(db_path) if db_path else REPO_ROOT / "data" / "edge_production.db"
    repo = None
    if target_db.exists():
        try:
            repo = IncidentRepository(db_path=target_db)
        except Exception:
            repo = None

    ring = key_ring or EvidenceKeyRing.from_env()
    encryptor = EvidenceEncryptor(key_ring=ring, repository=repo)
    active_kid = ring.active_kid

    print(f"Scanning directory: {ev_dir}")
    print(f"Active Key ID:      {active_kid}")
    print(f"Dry Run:            {dry_run}")

    inspected_files = 0
    migrated_files = 0
    skipped_already_encrypted = 0
    bytes_encrypted = 0
    migrated_items: List[Dict[str, Any]] = []

    # 1. Walk directory for evidence files
    for root, _, files in os.walk(ev_dir):
        for f in files:
            file_path = Path(root) / f
            # Ignore temporary files
            if file_path.suffix in (".tmp", ".reenc"):
                continue

            inspected_files += 1
            if encryptor.is_encrypted_file(file_path):
                skipped_already_encrypted += 1
                continue

            sz = file_path.stat().st_size
            plaintext_bytes = file_path.read_bytes()
            pre_hash = hashlib.sha256(plaintext_bytes).hexdigest()

            # Attempt to determine incident_id from parent folder name or file prefix
            incident_id = "INC-UNKNOWN"
            if file_path.parent.name.startswith("INC-"):
                incident_id = file_path.parent.name
            elif "_" in file_path.stem and file_path.stem.split("_")[0].startswith("INC"):
                incident_id = file_path.stem.split("_")[0]

            enc_path = file_path.with_name(file_path.name + ".enc") if not file_path.name.endswith(".enc") else file_path

            if not dry_run:
                # Encrypt bytes and write container
                envelope, digest = encryptor.encrypt_bytes(
                    plaintext=plaintext_bytes,
                    incident_id=incident_id,
                    filename=file_path.name,
                    kid=active_kid,
                )
                assert digest == pre_hash, "Plaintext SHA-256 pre-encryption mismatch!"

                # Atomic write to destination
                tmp_out = enc_path.with_suffix(enc_path.suffix + ".tmp")
                tmp_out.write_bytes(envelope)
                tmp_out.replace(enc_path)

                # Remove original unencrypted file if replacing and filename changed
                if replace_plaintext and enc_path != file_path and file_path.exists():
                    file_path.unlink()

                # Update database record if database exists
                if repo:
                    try:
                        with sqlite3.connect(str(target_db), timeout=5.0) as conn:
                            conn.execute(
                                """
                                UPDATE evidence
                                SET encrypted = 1,
                                    key_id = ?,
                                    encryption_algo = 'AES-256-GCM',
                                    source_path = ?
                                WHERE source_path = ? OR source_path = ?
                                """,
                                (active_kid, str(enc_path), str(file_path), str(enc_path)),
                            )
                    except Exception as e:
                        print(f"Warning: Failed to update DB evidence record for {file_path}: {e}")

            bytes_encrypted += sz
            migrated_files += 1
            migrated_items.append({
                "original_path": str(file_path),
                "encrypted_path": str(enc_path),
                "plaintext_sha256": pre_hash,
                "key_id": active_kid,
                "size_bytes": sz,
            })

    elapsed_s = round(time.monotonic() - start_ts, 3)
    if repo:
        try:
            repo.close()
        except Exception:
            pass

    summary = {
        "status": "COMPLETED",
        "dry_run": dry_run,
        "active_key_id": active_kid,
        "files_inspected": inspected_files,
        "files_migrated": migrated_files,
        "already_encrypted_skipped": skipped_already_encrypted,
        "total_bytes_encrypted": bytes_encrypted,
        "duration_seconds": elapsed_s,
        "migrated_items": migrated_items,
    }

    print(f"\n[OK] Migration finished in {elapsed_s}s:")
    print(f"     Inspected: {inspected_files}")
    print(f"     Migrated:  {migrated_files}")
    print(f"     Skipped:   {skipped_already_encrypted} (already encrypted)")
    print(f"     Bytes:     {bytes_encrypted} bytes")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Sentinel-AI Evidence Encryption Migration Tool")
    parser.add_argument("--evidence-dir", type=str, default="data/evidence", help="Directory containing evidence files")
    parser.add_argument("--db-path", type=str, default=None, help="Database path for evidence record updates")
    parser.add_argument("--dry-run", action="store_true", help="Simulate migration without modifying files")
    parser.add_argument("--operator-id", type=str, default="migration_admin", help="Operator performing migration")
    args = parser.parse_args()

    res = migrate_unencrypted_evidence(
        evidence_dir=Path(args.evidence_dir),
        db_path=Path(args.db_path) if args.db_path else None,
        dry_run=args.dry_run,
        operator_id=args.operator_id,
    )
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
