#!/usr/bin/env python3
"""
Standalone Zero-Dependency Evidence Bundle Verifier (Phase 6Q).
================================================================
Allows external researchers, auditors, or court analysts to independently
verify a Sentinel-AI incident evidence bundle without installing the Edge-AI platform.

Requires only the Python standard library (Python 3.8+).

Usage:
    python scripts/verify_bundle.py --bundle data/evidence_bundles/INC-001
    python scripts/verify_bundle.py --bundle /path/to/bundle --key <secret_or_file>
"""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple


def sha256_file_plaintext(path: Path) -> str:
    """Computes SHA-256 of file, extracting plaintext digest if Phase 6K encrypted container."""
    if not path.exists() or path.stat().st_size == 0:
        return hashlib.sha256(b"").hexdigest()

    # Check for Phase 6K encrypted container header
    if path.stat().st_size >= 46:
        try:
            with open(path, "rb") as f:
                if f.read(12) == b"SEN_EVID_V1\x00":
                    kid_len = f.read(1)[0]
                    f.seek(kid_len, 1)
                    nonce_len = f.read(1)[0]
                    f.seek(nonce_len, 1)
                    raw_hash = f.read(32)
                    return raw_hash.hex()
        except Exception:
            pass

    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_canonical_manifest_hash(manifest_dict: Dict[str, Any]) -> str:
    """Computes SHA-256 over canonical manifest item list and chain metadata."""
    items = manifest_dict.get("items", [])
    canonical_items = sorted(
        [
            {
                "path": it["relative_path"],
                "sha256": it["sha256_hash"],
                "size": it.get("file_size_bytes", 0),
                "type": it.get("artifact_type", "UNKNOWN"),
            }
            for it in items
        ],
        key=lambda x: x["path"],
    )
    canonical_payload = {
        "incident_id": manifest_dict.get("incident_id", ""),
        "chain_index": manifest_dict.get("chain_index", 1),
        "prev_bundle_hash": manifest_dict.get("prev_bundle_hash", "0" * 64),
        "items": canonical_items,
    }
    raw_json = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()


def verify_bundle_standalone(
    bundle_dir: Path,
    expected_prev_hash: Optional[str] = None,
    key_str: Optional[str] = None,
    require_signature: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    manifest_file = bundle_dir / "manifest.json"
    if not manifest_file.exists():
        return "MISSING_ITEM", {"error": "manifest.json missing from bundle"}

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception as e:
        return "HASH_MISMATCH", {"error": f"Invalid manifest JSON: {e}"}

    items = manifest.get("items", [])
    stored_manifest_hash = manifest.get("manifest_hash", "")
    chain_index = manifest.get("chain_index", 1)
    prev_hash = manifest.get("prev_bundle_hash", "0" * 64)
    signature = manifest.get("signature")

    missing = []
    mismatch = []
    matched = []

    for it in items:
        rel_path = it.get("relative_path", "")
        exp_hash = it.get("sha256_hash", "")
        target = bundle_dir / rel_path

        if not target.exists():
            missing.append({"path": rel_path, "expected": exp_hash})
            continue

        act_hash = sha256_file_plaintext(target)
        if act_hash != exp_hash:
            mismatch.append({"path": rel_path, "expected": exp_hash, "actual": act_hash})
        else:
            matched.append({"path": rel_path, "sha256": act_hash})

    # Check manifest hash
    computed_manifest_hash = compute_canonical_manifest_hash(manifest)
    manifest_hash_ok = (computed_manifest_hash == stored_manifest_hash)

    # Check chain link
    chain_ok = True
    if expected_prev_hash and prev_hash != expected_prev_hash:
        chain_ok = False

    # Check signature
    sig_status = "UNSIGNED"
    if signature:
        if key_str:
            expected_sig = hmac.new(
                key_str.encode("utf-8"),
                stored_manifest_hash.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if hmac.compare_digest(expected_sig, signature):
                sig_status = "VALID"
            else:
                sig_status = "INVALID"
        else:
            sig_status = "UNVERIFIED_NO_KEY"
    elif require_signature:
        sig_status = "UNSIGNED"

    details = {
        "incident_id": manifest.get("incident_id"),
        "bundle_id": manifest.get("bundle_id"),
        "chain_index": chain_index,
        "prev_bundle_hash": prev_hash,
        "manifest_hash": stored_manifest_hash,
        "manifest_hash_valid": manifest_hash_ok,
        "chain_link_valid": chain_ok,
        "signature_status": sig_status,
        "items_total": len(items),
        "items_matched": len(matched),
        "items_mismatched": mismatch,
        "items_missing": missing,
    }

    if missing:
        return "MISSING_ITEM", details
    if mismatch or not manifest_hash_ok or not chain_ok or sig_status == "INVALID":
        return "HASH_MISMATCH", details
    if require_signature and sig_status == "UNSIGNED":
        return "UNSIGNED", details

    return "VERIFIED", details


def main() -> int:
    parser = argparse.ArgumentParser(description="Standalone Incident Evidence Bundle Verifier")
    parser.add_argument("--bundle", "-b", required=True, help="Path to evidence bundle directory")
    parser.add_argument("--prev-hash", "-p", default=None, help="Expected previous bundle hash for chain verification")
    parser.add_argument("--key", "-k", default=None, help="Secret signing key string or path to key file")
    parser.add_argument("--require-signature", action="store_true", help="Require valid digital signature")
    parser.add_argument("--json", action="store_true", help="Output JSON")

    args = parser.parse_args()
    bundle_path = Path(args.bundle)

    key_str = args.key
    if key_str and Path(key_str).exists():
        key_str = Path(key_str).read_text(encoding="utf-8").strip()

    status, details = verify_bundle_standalone(
        bundle_dir=bundle_path,
        expected_prev_hash=args.prev_hash,
        key_str=key_str,
        require_signature=args.require_signature,
    )

    if args.json:
        print(json.dumps({"status": status, "details": details}, indent=2))
    else:
        print("=" * 70)
        print(f"STANDALONE EVIDENCE BUNDLE VERIFICATION: {status}")
        print("=" * 70)
        print(f"Incident ID:    {details.get('incident_id')}")
        print(f"Manifest Hash:  {details.get('manifest_hash')}")
        print(f"Chain Index:    #{details.get('chain_index')} (Prev: {details.get('prev_bundle_hash')[:16]}...)")
        print(f"Items Verified: {details.get('items_matched')}/{details.get('items_total')}")
        print(f"Signature:      {details.get('signature_status')}")
        if details.get("items_mismatched"):
            print("\nMismatched Items:")
            for m in details["items_mismatched"]:
                print(f"  - {m['path']}: expected {m['expected'][:12]}..., got {m['actual'][:12]}...")
        if details.get("items_missing"):
            print("\nMissing Items:")
            for m in details["items_missing"]:
                print(f"  - {m['path']}")
        print("=" * 70)

    return 0 if status == "VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())
