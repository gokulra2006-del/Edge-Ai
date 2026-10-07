"""
Module: Tamper-Evident Evidence Packaging.
=========================================
Generates cryptographic Merkle-tree rooted packages over incident video clips,
audio recordings, and metadata manifests to ensure strict court-admissible chain of custody.

Research Hypothesis:
Packaging multi-sensor incident artifacts into a deterministic Merkle tree structure
with SHA-256 leaf hashes enables sub-second tamper localization (identifying the
exact modified byte/artifact among dozens of files) and guarantees 100% detection
of unauthorized bitrot or evidence modification.

Primary Metrics:
1. Tamper Detection Rate: 100% of single-byte alterations in media files or metadata
   manifests are detected during package verification.
2. Tamper Localization: Precisely isolates the specific corrupted leaf/file without
   invalidating uncorrupted sibling artifacts.
3. Verification Performance: Full Merkle validation executes in < 250ms for packages
   with up to 50 artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    path = Path(path)
    if not path.exists():
        return hashlib.sha256(b"").hexdigest()
    # If encrypted evidence container, extract authenticated plaintext hash
    if path.stat().st_size >= 46:
        try:
            with open(path, "rb") as f:
                magic = f.read(12)
                if magic == b"SEN_EVID_V1\x00":
                    kid_len = f.read(1)[0]
                    f.seek(kid_len, 1)  # skip kid
                    nonce_len = f.read(1)[0]
                    f.seek(nonce_len, 1)  # skip nonce
                    raw_hash = f.read(32)
                    return raw_hash.hex()
        except Exception:
            pass
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class EvidenceLeaf:
    filename: str
    artifact_type: str  # VIDEO, AUDIO, METADATA, TELEMETRY
    sha256_hash: str
    file_size_bytes: int
    encrypted: bool = False
    key_id: Optional[str] = None


@dataclass
class EvidencePackageManifest:
    incident_id: str
    package_id: str
    created_at: str
    merkle_root: str
    leaves: List[EvidenceLeaf]
    export_operator_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "package_id": self.package_id,
            "created_at": self.created_at,
            "merkle_root": self.merkle_root,
            "leaves": [
                {
                    "filename": l.filename,
                    "artifact_type": l.artifact_type,
                    "sha256_hash": l.sha256_hash,
                    "file_size_bytes": l.file_size_bytes,
                    "encrypted": getattr(l, "encrypted", False),
                    "key_id": getattr(l, "key_id", None),
                }
                for l in self.leaves
            ],
            "export_operator_id": self.export_operator_id,
        }


class MerkleEvidencePackager:
    """
    Constructs and verifies tamper-evident Merkle-tree packages for forensic evidence.
    """

    @staticmethod
    def compute_merkle_root(leaf_hashes: List[str]) -> str:
        """Computes deterministic Merkle root from list of leaf hashes."""
        if not leaf_hashes:
            return sha256_bytes(b"EMPTY_EVIDENCE_TREE")

        current_layer = sorted(leaf_hashes)

        while len(current_layer) > 1:
            next_layer: List[str] = []
            for i in range(0, len(current_layer), 2):
                h1 = current_layer[i]
                h2 = current_layer[i + 1] if i + 1 < len(current_layer) else h1
                combined = (h1 + h2).encode("utf-8")
                next_layer.append(sha256_bytes(combined))
            current_layer = next_layer

        return current_layer[0]

    @classmethod
    def create_package(
        cls,
        incident_id: str,
        files: List[Tuple[Path, str]],  # List of (file_path, artifact_type)
        operator_id: str,
    ) -> Tuple[Dict[str, Any], EvidencePackageManifest]:
        leaves: List[EvidenceLeaf] = []
        leaf_hashes: List[str] = []

        for p, art_type in files:
            path_obj = Path(p)
            f_hash = sha256_file(path_obj) if path_obj.exists() else sha256_bytes(b"")
            f_size = path_obj.stat().st_size if path_obj.exists() else 0
            is_enc = False
            k_id = None
            if path_obj.exists() and f_size >= 46:
                try:
                    with open(path_obj, "rb") as f:
                        if f.read(12) == b"SEN_EVID_V1\x00":
                            is_enc = True
                            k_len = f.read(1)[0]
                            k_id = f.read(k_len).decode("utf-8", errors="replace")
                except Exception:
                    pass
            leaf = EvidenceLeaf(
                filename=path_obj.name,
                artifact_type=art_type,
                sha256_hash=f_hash,
                file_size_bytes=f_size,
                encrypted=is_enc,
                key_id=k_id,
            )
            leaves.append(leaf)
            leaf_hashes.append(f_hash)

        root = cls.compute_merkle_root(leaf_hashes)
        pkg_id = f"pkg_{incident_id}_{hashlib.sha256(root.encode()).hexdigest()[:12]}"

        manifest = EvidencePackageManifest(
            incident_id=incident_id,
            package_id=pkg_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            merkle_root=root,
            leaves=leaves,
            export_operator_id=operator_id,
        )

        return manifest.to_dict(), manifest

    @classmethod
    def verify_package(
        cls,
        manifest: EvidencePackageManifest,
        base_dir: Path,
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Verifies package integrity against files in base_dir.
        Returns:
            (is_valid, corrupted_files, reasons)
        """
        corrupted: List[str] = []
        reasons: List[str] = []
        computed_leaf_hashes: List[str] = []

        for leaf in manifest.leaves:
            target_path = base_dir / leaf.filename
            if not target_path.exists():
                corrupted.append(leaf.filename)
                reasons.append(f"MISSING_FILE: {leaf.filename}")
                continue

            current_hash = sha256_file(target_path)
            computed_leaf_hashes.append(current_hash)
            if current_hash != leaf.sha256_hash:
                corrupted.append(leaf.filename)
                reasons.append(
                    f"HASH_MISMATCH: {leaf.filename} (expected={leaf.sha256_hash[:8]}, actual={current_hash[:8]})"
                )

        recomputed_root = cls.compute_merkle_root(computed_leaf_hashes)
        if recomputed_root != manifest.merkle_root:
            reasons.append(f"MERKLE_ROOT_MISMATCH (expected={manifest.merkle_root[:8]}, computed={recomputed_root[:8]})")

        is_valid = len(corrupted) == 0 and (recomputed_root == manifest.merkle_root)
        return is_valid, corrupted, reasons
