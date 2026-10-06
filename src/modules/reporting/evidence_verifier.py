"""Cryptographic evidence verification service for tamper detection."""

from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Any

from src.modules.database.governed_store import IncidentRepository


def compute_sha256(file_path: Path | str) -> str:
    """Compute SHA-256 digest of file in streaming chunks."""
    p = Path(file_path)
    hasher = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class EvidenceVerifier:
    """Verifies evidence file integrity against SQLite tamper-evident audit hashes."""

    def __init__(self, repository: IncidentRepository):
        self.repository = repository

    def verify_all_evidence(self) -> dict[str, Any]:
        """Re-hash all evidence files referenced in SQLite evidence table and report any mismatch."""
        rows = self.repository.rows("evidence")
        total = len(rows)
        matched = 0
        tampered: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []

        for r in rows:
            ev_id = r["id"]
            inc_id = r["incident_id"]
            src_path_str = r["source_path"]
            expected_sha = r["sha256"]
            p = Path(src_path_str)

            if not p.exists():
                missing.append({
                    "id": ev_id,
                    "incident_id": inc_id,
                    "path": str(p),
                    "expected_sha256": expected_sha,
                    "reason": "File not found on filesystem"
                })
                continue

            actual_sha = compute_sha256(p)
            if actual_sha != expected_sha:
                tampered.append({
                    "id": ev_id,
                    "incident_id": inc_id,
                    "path": str(p),
                    "expected_sha256": expected_sha,
                    "actual_sha256": actual_sha,
                    "reason": "Cryptographic digest mismatch (file tampered or modified)"
                })
            else:
                matched += 1

        is_verified = len(tampered) == 0 and len(missing) == 0
        return {
            "verified": is_verified,
            "total_checked": total,
            "matched": matched,
            "tampered_count": len(tampered),
            "missing_count": len(missing),
            "tampered": tampered,
            "missing": missing,
        }

    def verify_manifest(self, manifest_path: Path | str) -> dict[str, Any]:
        """Verify an exported evidence package manifest.json."""
        import json
        m_path = Path(manifest_path)
        if not m_path.exists():
            return {
                "verified": False,
                "error": f"Manifest not found: {m_path}",
                "total_checked": 0,
                "matched": 0,
                "tampered": [],
                "missing": []
            }

        manifest = json.loads(m_path.read_text(encoding="utf-8"))
        evidence = manifest.get("evidence", [])
        matched = 0
        tampered = []
        missing = []

        for item in evidence:
            rel_file = item["file"]
            expected_sha = item["sha256"]
            target_file = m_path.parent / rel_file

            if not target_file.exists():
                missing.append({"file": rel_file, "expected_sha256": expected_sha})
                continue

            actual_sha = compute_sha256(target_file)
            if actual_sha != expected_sha:
                tampered.append({
                    "file": rel_file,
                    "expected_sha256": expected_sha,
                    "actual_sha256": actual_sha
                })
            else:
                matched += 1

        return {
            "verified": len(tampered) == 0 and len(missing) == 0,
            "total_checked": len(evidence),
            "matched": matched,
            "tampered_count": len(tampered),
            "missing_count": len(missing),
            "tampered": tampered,
            "missing": missing,
        }
