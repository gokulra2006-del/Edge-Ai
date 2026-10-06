"""
Test Suite: Phase 6 Item 6 - Tamper-Evident Evidence Packaging.
==============================================================
Validates Merkle-tree rooted evidence packaging, 100% tamper detection
of single-byte alterations, and exact corruption localization.
"""
from __future__ import annotations

from pathlib import Path
import pytest
from src.modules.reporting.evidence_package import MerkleEvidencePackager


def test_merkle_evidence_package_creation_and_tamper_detection(tmp_path):
    """
    Hypothesis: Creating a Merkle evidence package yields deterministic roots,
    and modifying a single byte in any artifact immediately triggers tamper
    detection and isolates the corrupted file without failing unaffected leaves.
    """
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    # Create dummy incident files
    cam_file = evidence_dir / "camera_clip_01.mp4"
    cam_file.write_bytes(b"Simulated H.264 video payload stream 0123456789")

    audio_file = evidence_dir / "audio_snippet_01.wav"
    audio_file.write_bytes(b"Simulated WAV 16kHz PCM audio stream 9876543210")

    meta_file = evidence_dir / "incident_meta.json"
    meta_file.write_text('{"event": "CRASH", "confidence": 0.94}', encoding="utf-8")

    files = [
        (cam_file, "VIDEO"),
        (audio_file, "AUDIO"),
        (meta_file, "METADATA"),
    ]

    # 1. Package creation
    pkg_dict, manifest = MerkleEvidencePackager.create_package(
        incident_id="INC-2026-901",
        files=files,
        operator_id="operator_dave",
    )

    assert manifest.merkle_root is not None
    assert len(manifest.merkle_root) == 64
    assert len(manifest.leaves) == 3

    # 2. Verify pristine package passes
    is_valid, corrupted, reasons = MerkleEvidencePackager.verify_package(manifest, evidence_dir)
    assert is_valid is True
    assert len(corrupted) == 0
    assert len(reasons) == 0

    # 3. Simulate tamper: modify 1 byte in audio_snippet_01.wav
    tampered_bytes = bytearray(audio_file.read_bytes())
    tampered_bytes[0] ^= 0xFF  # Flip bits of first byte
    audio_file.write_bytes(tampered_bytes)

    # 4. Verify tampered package detects corruption and isolates exact file
    is_valid_after, corrupted_after, reasons_after = MerkleEvidencePackager.verify_package(manifest, evidence_dir)
    assert is_valid_after is False
    assert corrupted_after == ["audio_snippet_01.wav"]
    assert any("HASH_MISMATCH: audio_snippet_01.wav" in r for r in reasons_after)
    assert any("MERKLE_ROOT_MISMATCH" in r for r in reasons_after)


def test_missing_evidence_file_localization(tmp_path):
    """
    Hypothesis: Deleting an evidence file is localized as MISSING_FILE without crashing.
    """
    evidence_dir = tmp_path / "evidence_del"
    evidence_dir.mkdir()

    f1 = evidence_dir / "clip_a.mp4"
    f1.write_bytes(b"Sample A")
    f2 = evidence_dir / "clip_b.mp4"
    f2.write_bytes(b"Sample B")

    _, manifest = MerkleEvidencePackager.create_package(
        incident_id="INC-DEL-1",
        files=[(f1, "VIDEO"), (f2, "VIDEO")],
        operator_id="operator_bob",
    )

    # Delete clip_a.mp4
    f1.unlink()

    is_valid, corrupted, reasons = MerkleEvidencePackager.verify_package(manifest, evidence_dir)
    assert is_valid is False
    assert "clip_a.mp4" in corrupted
    assert any("MISSING_FILE: clip_a.mp4" in r for r in reasons)
