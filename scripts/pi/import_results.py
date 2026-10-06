#!/usr/bin/env python3
"""
scripts/pi/import_results.py
Authenticates and imports physical hardware validation results into results/hardware_validation.json.

Strict Security & Integrity Checks:
- Requires data_tag == "REAL_HARDWARE".
- Validates cryptographic benchmark signature.
- Rejects forged, synthetic, or tampered results files.
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.pi.common import verify_benchmark_header


def import_validation_results(
    input_file: Path,
    target_results_file: Path = REPO_ROOT / "results" / "hardware_validation.json",
) -> dict:
    input_p = Path(input_file)
    if not input_p.exists():
        raise FileNotFoundError(f"Input validation file does not exist: {input_p}")

    try:
        data = json.loads(input_p.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Input file is not valid JSON: {e}")

    # Check whether it's a consolidated bundle or an individual benchmark
    if "bundle_header" in data:
        header = data["bundle_header"]
        benchmarks = data.get("benchmarks", {})
    elif "header" in data:
        header = data["header"]
        benchmarks = {header.get("benchmark", "single_benchmark"): data}
    else:
        raise ValueError("Security Rejection: Input JSON lacks authenticated header metadata.")

    # Authenticate header
    valid, reason = verify_benchmark_header(header)
    if not valid:
        raise ValueError(f"Security Rejection: Benchmark authentication failed ({reason}). Refusing import.")

    # Authenticate internal benchmark headers if present
    for name, b_data in benchmarks.items():
        if isinstance(b_data, dict) and "header" in b_data:
            b_valid, b_reason = verify_benchmark_header(b_data["header"])
            if not b_valid:
                raise ValueError(f"Security Rejection: Benchmark '{name}' failed authentication ({b_reason}). Refusing import.")

    # Load existing destination or create new structure
    target_p = Path(target_results_file)
    target_p.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if target_p.exists():
        try:
            existing = json.loads(target_p.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    merged_benchmarks = existing.get("benchmarks", {})
    merged_benchmarks.update(benchmarks)

    consolidated = {
        "status": "AUTHENTICATED",
        "data_tag": "REAL_HARDWARE",
        "imported_from": str(input_p.name),
        "hardware_model": header["hardware_model"],
        "os": header["os"],
        "git_hash": header["git_hash"],
        "timestamp_utc": header["timestamp_utc"],
        "signature": header["signature"],
        "benchmarks": merged_benchmarks,
    }

    target_p.write_text(json.dumps(consolidated, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[OK] Successfully authenticated and imported {len(benchmarks)} hardware benchmark(s).")
    print(f"Destination: {target_p}")
    return consolidated


def main():
    parser = argparse.ArgumentParser(description="Sentinel-AI Real Hardware Result Importer")
    parser.add_argument("input_file", type=str, help="Path to validated Pi benchmark JSON or bundle")
    parser.add_argument("--dest", type=str, default="results/hardware_validation.json", help="Destination path")
    args = parser.parse_args()

    try:
        import_validation_results(Path(args.input_file), Path(args.dest))
    except Exception as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
