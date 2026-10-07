"""CLI entry point for storage retention, WAL management, and safe cleanup."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.modules.database.governed_store import IncidentRepository
from src.modules.storage.storage_safety import (
    StorageRetentionEngine,
    WalCheckpointManager,
    StorageSafetyStatus,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sentinel-AI Storage Retention and Safety Manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Cleanup
    clean_p = subparsers.add_parser("cleanup", help="Run safe data retention cleanup")
    clean_p.add_argument(
        "--policy",
        choices=["all", "telemetry", "dvr", "evidence", "reports", "logs", "outbox"],
        default="all",
        help="Target retention policy to execute",
    )
    clean_p.add_argument("--dry-run", action="store_true", help="Simulate without deleting files or rows")
    clean_p.add_argument("--role", default="COMMANDER", help="Operator role for authorization")

    # 2. Checkpoint
    ckpt_p = subparsers.add_parser("checkpoint", help="Execute SQLite WAL checkpoint")
    ckpt_p.add_argument(
        "--mode",
        choices=["PASSIVE", "TRUNCATE", "FULL", "RESTART"],
        default="PASSIVE",
        help="Checkpoint mode",
    )
    ckpt_p.add_argument("--role", default="ENGINEER", help="Operator role for authorization")

    # 3. Status
    subparsers.add_parser("status", help="Display storage health and subsystem volume sizes")

    # 4. Logs
    logs_p = subparsers.add_parser("logs", help="Display recent storage cleanup history")
    logs_p.add_argument("--limit", type=int, default=10, help="Number of records to show")

    # 5. Encrypt Evidence Migration (Phase 6K)
    enc_p = subparsers.add_parser("encrypt-evidence", help="Migrate unencrypted evidence files to AES-256-GCM authenticated encryption")
    enc_p.add_argument("--evidence-dir", default="data/evidence", help="Directory of evidence files")
    enc_p.add_argument("--dry-run", action="store_true", help="Simulate encryption without modifying files")
    enc_p.add_argument("--role", default="ENGINEER", help="Operator role for authorization")

    args = parser.parse_args()

    repo = IncidentRepository()
    try:
        engine = StorageRetentionEngine(repository=repo)
        status_helper = StorageSafetyStatus(engine=engine)

        if args.command == "status":
            stat = status_helper.get_status()
            print(json.dumps(stat, indent=2))
            return

        elif args.command == "encrypt-evidence":
            role_upper = args.role.upper()
            if role_upper not in ("COMMANDER", "ENGINEER"):
                print(f"Error: Role {args.role} is not authorized to execute evidence encryption migration.", file=sys.stderr)
                sys.exit(1)
            from scripts.storage.migrate_evidence_encryption import migrate_unencrypted_evidence
            res = migrate_unencrypted_evidence(
                evidence_dir=args.evidence_dir,
                db_path=repo.db_path,
                dry_run=args.dry_run,
                operator_id=args.role,
            )
            print(json.dumps(res, indent=2))
            return

        elif args.command == "checkpoint":
            role_upper = args.role.upper()
            if role_upper not in ("COMMANDER", "ENGINEER"):
                print(f"Error: Role {args.role} is not authorized to execute WAL checkpointing.", file=sys.stderr)
                sys.exit(1)
            res = engine.wal_manager.checkpoint(mode=args.mode)
            print(json.dumps(res, indent=2))
            if not res.get("success"):
                sys.exit(1)
            return

        elif args.command == "cleanup":
            role_upper = args.role.upper()
            if role_upper not in ("COMMANDER", "ENGINEER"):
                print(f"Error: Role {args.role} is not authorized to execute storage cleanup.", file=sys.stderr)
                sys.exit(1)

            dry = args.dry_run
            policy = args.policy
            if policy == "all":
                res = engine.run_full_cleanup(dry_run=dry)
            elif policy == "telemetry":
                res = engine.archive_telemetry(dry_run=dry)
            elif policy == "dvr":
                res = engine.evict_dvr(dry_run=dry)
            elif policy == "evidence":
                res = engine.cleanup_evidence(dry_run=dry)
            elif policy == "reports":
                res = engine.cleanup_reports(dry_run=dry)
            elif policy == "logs":
                res = engine.cleanup_logs(dry_run=dry)
            elif policy == "outbox":
                res = engine.cleanup_outbox(dry_run=dry)

            print(json.dumps(res, indent=2))
            return

        elif args.command == "logs":
            import sqlite3
            with sqlite3.connect(str(repo.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM storage_cleanup_logs ORDER BY id DESC LIMIT ?",
                    (args.limit,)
                )
                rows = [dict(r) for r in cursor.fetchall()]
                print(json.dumps(rows, indent=2))
            return
    finally:
        repo.close()


if __name__ == "__main__":
    main()
