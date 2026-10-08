"""CLI entrypoint for python -m evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from src.modules.database.governed_store import IncidentRepository
from src.modules.evidence.verifier import EvidenceBundleVerifier


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evidence",
        description="Sentinel-AI Evidence Bundle & Cryptographic Verification Tool (Phase 6Q)",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Evidence subcommands")

    verify_parser = subparsers.add_parser("verify", help="Verify incident evidence bundle")
    verify_parser.add_argument("--incident", "-i", required=True, help="Incident ID to verify")
    verify_parser.add_argument("--bundle-dir", "-b", default=None, help="Path to evidence bundle directory")
    verify_parser.add_argument("--key", "-k", default=None, help="Signature secret key or path to key file")
    verify_parser.add_argument("--require-signature", action="store_true", help="Fail if bundle is unsigned")
    verify_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args()

    if args.subcommand != "verify":
        parser.print_help()
        return 2

    # Load signing key from file if path provided
    key_val = args.key
    if key_val and Path(key_val).exists():
        key_val = Path(key_val).read_text(encoding="utf-8").strip()

    # Initialize repository if default db exists
    repo = None
    default_db = Path("data/governed_incident_store.db")
    if default_db.exists():
        try:
            repo = IncidentRepository(default_db)
        except Exception:
            repo = None

    bundle_target = args.bundle_dir or args.incident
    verifier = EvidenceBundleVerifier(repository=repo)
    result = verifier.verify_bundle(
        bundle_path_or_id=bundle_target,
        signing_key=key_val,
        require_signature=args.require_signature,
    )

    if repo:
        repo.close()

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.to_text_report())

    return 0 if result.overall_status == "VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())
