"""
CLI Interface for Sentinel-AI Database Maintenance, Backup, and Recovery.
"""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

from src.modules.maintenance.backup import (
    create_online_backup,
    restore_backup,
    verify_database_integrity,
    BackupError,
)
from src.modules.maintenance.recovery import run_startup_recovery


def main() -> None:
    parser = argparse.ArgumentParser(description="Sentinel-AI Maintenance & Backup Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Backup
    p_backup = subparsers.add_parser("backup", help="Create an online non-blocking SQLite backup")
    p_backup.add_argument("--source", default="data/emergency_events.db", help="Source database path")
    p_backup.add_argument("--target", required=True, help="Target backup file path (.db)")

    # Restore
    p_restore = subparsers.add_parser("restore", help="Restore database from backup snapshot")
    p_restore.add_argument("--source", required=True, help="Backup snapshot path")
    p_restore.add_argument("--target", default="data/emergency_events.db", help="Destination database path")
    p_restore.add_argument("--no-verify", action="store_true", help="Skip checksum verification")

    # Verify
    p_verify = subparsers.add_parser("verify", help="Run SQLite integrity check on database")
    p_verify.add_argument("--db", default="data/emergency_events.db", help="Database file to verify")

    # Recovery
    p_recovery = subparsers.add_parser("recovery", help="Run startup / crash recovery audit")
    p_recovery.add_argument("--db", default="data/emergency_events.db", help="Database file path")

    args = parser.parse_args()

    try:
        if args.command == "backup":
            res = create_online_backup(args.source, args.target)
            print(json.dumps(res, indent=2))
        elif args.command == "restore":
            res = restore_backup(args.source, args.target, verify_checksum=not args.no_verify)
            print(json.dumps(res, indent=2))
        elif args.command == "verify":
            res = verify_database_integrity(args.db)
            print(json.dumps(res, indent=2))
            if res["status"] != "PASSED":
                sys.exit(1)
        elif args.command == "recovery":
            res = run_startup_recovery(args.db)
            print(json.dumps(res, indent=2))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
