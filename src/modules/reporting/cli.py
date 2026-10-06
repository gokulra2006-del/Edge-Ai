"""Command-line interface for Sentinel-AI reporting and compliance verification."""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

from src.config.settings import CONFIG
from src.modules.database.governed_store import IncidentRepository
from src.modules.reporting.report_service import ReportService
from src.modules.reporting.evidence_verifier import EvidenceVerifier


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reports",
        description="Sentinel-AI Compliance Reporting & Forensic Verification CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. generate
    gen_p = subparsers.add_parser("generate", help="Generate a compliance or operations report")
    gen_p.add_argument("--type", dest="report_type", default="monthly", choices=["monthly", "assurance", "drift", "health", "evidence", "csv"], help="Type of report to generate")
    gen_p.add_argument("--month", dest="month", default=None, help="Target month in YYYY-MM format for monthly operations report")
    gen_p.add_argument("--format", dest="format", default="html", choices=["html", "pdf"], help="Output format (html or pdf)")
    gen_p.add_argument("--operator", dest="operator_id", default="commander", help="Operator ID generating the report")
    gen_p.add_argument("--role", dest="role", default="COMMANDER", help="Operator role for authorization")
    gen_p.add_argument("--output-dir", dest="output_dir", default="reports", help="Directory where reports are stored")

    # 2. verify-evidence
    ver_p = subparsers.add_parser("verify-evidence", help="Re-hash evidence files to detect tampering or missing artifacts")
    ver_p.add_argument("--manifest", dest="manifest", default=None, help="Optional path to exported evidence package manifest.json")

    # 3. list
    subparsers.add_parser("list", help="List generated reports from manifest")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    repo = IncidentRepository(Path(CONFIG.db_path))
    try:
        report_svc = ReportService(repo, reports_dir=args.output_dir if hasattr(args, "output_dir") else "reports")

        if args.command == "generate":
            as_pdf = (args.format.lower() == "pdf")
            try:
                res = report_svc.generate(
                    report_type=args.report_type,
                    operator_id=args.operator_id,
                    role=args.role,
                    month=args.month,
                    as_pdf=as_pdf,
                )
                print(f"[SUCCESS] Report generated successfully.")
                print(f"  Report ID : {res['report']['report_id']}")
                print(f"  Type      : {res['report']['report_type']}")
                print(f"  Format    : {res['report']['format'].upper()}")
                print(f"  File Path : {res['path']}")
                print(f"  SHA-256   : {res['report']['sha256']}")
                return 0
            except Exception as exc:
                print(f"[ERROR] Failed to generate report: {exc}", file=sys.stderr)
                return 1

        elif args.command == "verify-evidence":
            verifier = EvidenceVerifier(repo)
            if args.manifest:
                print(f"Verifying evidence package manifest: {args.manifest}")
                result = verifier.verify_manifest(args.manifest)
            else:
                print("Verifying all active database evidence records against filesystem...")
                result = verifier.verify_all_evidence()

            print(f"Total files checked : {result['total_checked']}")
            print(f"Cryptographic match : {result['matched']}")
            print(f"Tampered files      : {result['tampered_count']}")
            print(f"Missing files       : {result['missing_count']}")

            if result["tampered"]:
                print("\n[CRITICAL] Tampered Evidence Files Detected:")
                for t in result["tampered"]:
                    print(f"  - Item #{t.get('id', '?')} ({t.get('path', t.get('file'))})")
                    print(f"    Expected: {t['expected_sha256']}")
                    print(f"    Actual  : {t['actual_sha256']}")

            if result["missing"]:
                print("\n[WARNING] Missing Evidence Files Detected:")
                for m in result["missing"]:
                    print(f"  - Item #{m.get('id', '?')} ({m.get('path', m.get('file'))})")

            if result["verified"]:
                print("\n[VERIFIED] All evidence files match cryptographic audit digests.")
                return 0
            else:
                print("\n[FAIL] Cryptographic integrity verification failed.")
                return 1

        elif args.command == "list":
            reports = report_svc.list_reports()
            if not reports:
                print("No reports generated yet.")
                return 0
            print(f"Found {len(reports)} generated report(s):")
            for r in reports:
                print(f"  [{r.get('generated_at', '')[:19]}] {r.get('report_id')} ({r.get('report_type')}, {r.get('format')}) -> {r.get('filename')}")
            return 0

        return 0
    finally:
        repo.close()


if __name__ == "__main__":
    sys.exit(main())
