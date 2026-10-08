"""Comprehensive test suite for Phase 6Q: Tamper-Evident Incident Evidence Bundles.

Verifies:
1. Clean bundle verification (all item hashes match, chain links correctly, replay reproduces decision -> VERIFIED).
2. Evidence file tampering (single byte edit in audio or sensor timeline -> HASH_MISMATCH).
3. Decision record tampering (altering stored predictions or risk scores -> HASH_MISMATCH).
4. Report file tampering (modifying forensic report.html -> HASH_MISMATCH).
5. Missing artifact detection (deleting keyframe image -> MISSING_ITEM).
6. Hash chain break & reordering (manipulating prev_bundle_hash or chain_index -> HASH_MISMATCH with chain error).
7. Replay mismatch detection (tampered telemetry causes replay engine output divergence -> REPLAY_MISMATCH).
8. Digital signature verification (valid HMAC matches, wrong key fails, missing signature flagged -> UNSIGNED).
9. Encrypted evidence plaintext hashing (Phase 6K SEN_EVID_V1 magic container plaintext hash verification).
10. CLI invocation via `python -m evidence verify --incident <id>`.
11. Standalone researcher verifier script `scripts/verify_bundle.py`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

from src.modules.database.governed_store import IncidentRepository
from src.modules.evidence.bundle import (
    EvidenceBundleBuilder,
    EvidenceBundleManifest,
    compute_file_sha256,
)
from src.modules.evidence.verifier import (
    EvidenceBundleVerifier,
    VerificationStatus,
)


@pytest.fixture
def test_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        db_path = tmp_path / "test_governed.db"
        bundles_dir = tmp_path / "evidence_bundles"
        bundles_dir.mkdir(parents=True, exist_ok=True)

        repo = IncidentRepository(db_path=db_path)
        builder = EvidenceBundleBuilder(repository=repo, bundles_dir=str(bundles_dir))
        verifier = EvidenceBundleVerifier(repository=repo, bundles_dir=str(bundles_dir))

        yield {
            "tmpdir": tmp_path,
            "repo": repo,
            "builder": builder,
            "verifier": verifier,
            "bundles_dir": bundles_dir,
        }

        repo.close()


def create_mock_incident(repo: IncidentRepository, incident_id: str = "INC-TEST-6Q-001") -> str:
    """Seeds a governed incident record with events and predictions."""
    # Insert directly into incidents table to ensure exact custom ID
    from src.modules.database.governed_store import utc_now
    now = utc_now()
    repo.writer.submit(
        lambda c: c.execute(
            "INSERT OR REPLACE INTO incidents(incident_id,incident_uuid,event_type,zone_id,status,created_at,updated_at,assurance_level) VALUES(?,?,?,?,?,?,?,?)",
            (incident_id, f"uuid-{incident_id}", "COLLISION", "ZONE_B_INTERSECTION", "OPEN", now, now, "FULL")
        )
    )
    repo.writer.drain()

    repo.add_prediction(
        incident_id,
        "COLLISION",
        0.94,
        "live-fusion-v1",
        {
            "ood_status": "IN_DISTRIBUTION",
            "reason_codes": [],
            "risk_factors": {"high_deceleration": 0.85, "audio_screech": 0.9},
        },
    )
    repo.writer.drain()
    return incident_id


def test_clean_bundle_verification(test_env):
    """Clean bundle building and verification produces VERIFIED status with no divergences."""
    repo = test_env["repo"]
    builder = test_env["builder"]
    verifier = test_env["verifier"]

    incident_id = "INC-CLEAN-001"
    create_mock_incident(repo, incident_id)

    bundle_dir, manifest = builder.build_bundle(incident_id, sign_key="sec_test_key_123")
    assert bundle_dir.exists()
    assert (bundle_dir / "manifest.json").exists()
    assert manifest.signature is not None

    res = verifier.verify_bundle(incident_id, key="sec_test_key_123", require_signature=True)
    assert res.overall_status == "VERIFIED"
    items_by_path = {it.relative_path: it for it in res.item_results}
    assert items_by_path["sensor_timeline.json"].status == "MATCH"
    assert items_by_path["audio.wav"].status == "MATCH"
    assert items_by_path["decision_record.json"].status == "MATCH"
    assert items_by_path["response_plan.json"].status == "MATCH"
    assert items_by_path["report.html"].status == "MATCH"
    assert res.chain_result.status == "VALID"
    assert res.replay_result.status == "MATCH"
    assert res.signature_status == "VALID"


def test_tamper_evidence_file(test_env):
    """Altering even a single byte of raw evidence file triggers HASH_MISMATCH."""
    repo = test_env["repo"]
    builder = test_env["builder"]
    verifier = test_env["verifier"]

    incident_id = "INC-TAMPER-EVID-002"
    create_mock_incident(repo, incident_id)

    bundle_dir, _ = builder.build_bundle(incident_id)
    audio_path = bundle_dir / "audio.wav"
    assert audio_path.exists()

    # Tamper audio file by appending bytes
    with open(audio_path, "ab") as f:
        f.write(b"\xde\xad\xbe\xef")

    res = verifier.verify_bundle(incident_id)
    assert res.overall_status == "HASH_MISMATCH"
    items_by_path = {it.relative_path: it for it in res.item_results}
    assert items_by_path["audio.wav"].status == "MISMATCH"


def test_tamper_decision_record(test_env):
    """Altering stored predictions or risk scores triggers HASH_MISMATCH."""
    repo = test_env["repo"]
    builder = test_env["builder"]
    verifier = test_env["verifier"]

    incident_id = "INC-TAMPER-DEC-003"
    create_mock_incident(repo, incident_id)

    bundle_dir, _ = builder.build_bundle(incident_id)
    dec_path = bundle_dir / "decision_record.json"

    data = json.loads(dec_path.read_text(encoding="utf-8"))
    data["event_type"] = "NORMAL"  # Maliciously downgrade incident
    dec_path.write_text(json.dumps(data), encoding="utf-8")

    res = verifier.verify_bundle(incident_id)
    assert res.overall_status == "HASH_MISMATCH"
    items_by_path = {it.relative_path: it for it in res.item_results}
    assert items_by_path["decision_record.json"].status == "MISMATCH"


def test_tamper_report(test_env):
    """Modifying the generated 5C report.html triggers HASH_MISMATCH."""
    repo = test_env["repo"]
    builder = test_env["builder"]
    verifier = test_env["verifier"]

    incident_id = "INC-TAMPER-REP-004"
    create_mock_incident(repo, incident_id)

    bundle_dir, _ = builder.build_bundle(incident_id)
    report_path = bundle_dir / "report.html"

    report_content = report_path.read_text(encoding="utf-8")
    tampered_content = report_content.replace("SENTINEL-AI", "MALICIOUS-AI").replace("Sentinel-AI", "Malicious-AI")
    if tampered_content == report_content:
        tampered_content = report_content + "<!-- tampered forensic marker -->"
    report_path.write_text(tampered_content, encoding="utf-8")

    res = verifier.verify_bundle(bundle_dir)
    assert res.overall_status == "HASH_MISMATCH"
    items_by_path = {it.relative_path: it for it in res.item_results}
    assert items_by_path["report.html"].status == "MISMATCH"


def test_missing_artifact(test_env):
    """Deleting an evidence bundle artifact causes MISSING_ITEM status."""
    repo = test_env["repo"]
    builder = test_env["builder"]
    verifier = test_env["verifier"]

    incident_id = "INC-MISSING-005"
    create_mock_incident(repo, incident_id)

    bundle_dir, _ = builder.build_bundle(incident_id)
    kf_path = bundle_dir / "camera_keyframes.jpg"
    assert kf_path.exists()
    kf_path.unlink()

    res = verifier.verify_bundle(incident_id)
    assert res.overall_status == "MISSING_ITEM"
    items_by_path = {it.relative_path: it for it in res.item_results}
    assert items_by_path["camera_keyframes.jpg"].status == "MISSING"


def test_chain_break_and_reordering(test_env):
    """Sequential bundles form an unbroken hash chain; tampering prev_bundle_hash fails verification."""
    repo = test_env["repo"]
    builder = test_env["builder"]
    verifier = test_env["verifier"]

    # Bundle 1
    inc1 = "INC-CHAIN-001"
    create_mock_incident(repo, inc1)
    dir1, m1 = builder.build_bundle(inc1)
    assert m1.chain_index == 1
    assert m1.prev_bundle_hash == "0" * 64

    # Bundle 2
    inc2 = "INC-CHAIN-002"
    create_mock_incident(repo, inc2)
    dir2, m2 = builder.build_bundle(inc2)
    assert m2.chain_index == 2
    assert m2.prev_bundle_hash == m1.manifest_hash

    # Both verify cleanly
    assert verifier.verify_bundle(inc1).overall_status == "VERIFIED"
    assert verifier.verify_bundle(inc2).overall_status == "VERIFIED"

    # Tamper Bundle 2's prev_bundle_hash in its manifest file
    m2_path = dir2 / "manifest.json"
    m2_data = json.loads(m2_path.read_text(encoding="utf-8"))
    m2_data["prev_bundle_hash"] = "a" * 64
    m2_path.write_text(json.dumps(m2_data), encoding="utf-8")

    res2 = verifier.verify_bundle(inc2)
    assert res2.overall_status == "HASH_MISMATCH"
    assert res2.chain_result.status == "BROKEN"


def test_replay_mismatch(test_env):
    """When stored inputs differ from replay outcome, REPLAY_MISMATCH is flagged."""
    repo = test_env["repo"]
    builder = test_env["builder"]
    verifier = test_env["verifier"]

    incident_id = "INC-REPLAY-FAIL-007"
    create_mock_incident(repo, incident_id)

    bundle_dir, manifest = builder.build_bundle(incident_id)

    # Invert sensor timeline to NORMAL and update manifest hash
    timeline_path = bundle_dir / "sensor_timeline.json"
    timeline_data = [
        {
            "step_idx": 0,
            "climate": {"temperature_c": 22.0},
            "gas_adc": {"mq2_ppm": 10.0, "smoke_detected": False},
            "imu": {"accel_mag_g": 0.05, "crash_detected": False},
            "audio": {"spl_db": 50.0, "siren_detected": False, "crash_detected": False},
            "vision": {"bbox_count": 0, "vehicles": []},
        }
    ]
    timeline_path.write_text(json.dumps(timeline_data, indent=2), encoding="utf-8")
    new_timeline_hash = compute_file_sha256(timeline_path)

    manifest_path = bundle_dir / "manifest.json"
    m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in m_data["items"]:
        if item["relative_path"] == "sensor_timeline.json":
            item["sha256_hash"] = new_timeline_hash
            item["file_size_bytes"] = timeline_path.stat().st_size

    # Re-canonicalize manifest so item hash check passes but replay diverges
    from src.modules.evidence.bundle import EvidenceBundleItem
    items_list = [
        EvidenceBundleItem(
            relative_path=it["relative_path"],
            artifact_type=it["artifact_type"],
            sha256_hash=it["sha256_hash"],
            file_size_bytes=it["file_size_bytes"],
        )
        for it in m_data["items"]
    ]
    manifest_obj = EvidenceBundleManifest(
        incident_id=m_data["incident_id"],
        bundle_id=m_data["bundle_id"],
        created_at=m_data["created_at"],
        chain_index=m_data["chain_index"],
        prev_bundle_hash=m_data["prev_bundle_hash"],
        items=items_list,
        manifest_hash="",
    )
    m_data["manifest_hash"] = manifest_obj.compute_canonical_manifest_hash()
    manifest_path.write_text(json.dumps(m_data, indent=2), encoding="utf-8")

    res = verifier.verify_bundle(bundle_dir)
    # Item hashes match, but sandboxed replay gives NORMAL while stored is DISPATCH_ALERT/ACCIDENT
    assert res.overall_status == "REPLAY_MISMATCH"
    assert res.replay_result.status == "MISMATCH"


def test_signature_verification(test_env):
    """Digital signature correctly distinguishes VALID, INVALID, and UNSIGNED."""
    repo = test_env["repo"]
    builder = test_env["builder"]
    verifier = test_env["verifier"]

    incident_id = "INC-SIG-008"
    create_mock_incident(repo, incident_id)

    builder.build_bundle(incident_id, sign_key="super_secret_local_key")

    # 1. Valid key
    res_valid = verifier.verify_bundle(incident_id, key="super_secret_local_key", require_signature=True)
    assert res_valid.overall_status == "VERIFIED"
    assert res_valid.signature_status == "VALID"

    # 2. Wrong key -> HASH_MISMATCH / Invalid signature
    res_wrong = verifier.verify_bundle(incident_id, key="wrong_unauthorized_key", require_signature=True)
    assert res_wrong.overall_status == "HASH_MISMATCH"
    assert res_wrong.signature_status == "INVALID"

    # 3. Build unsigned bundle and require signature -> UNSIGNED
    inc_unsigned = "INC-UNSIGNED-009"
    create_mock_incident(repo, inc_unsigned)
    builder.build_bundle(inc_unsigned, sign_key=None)

    res_unsig = verifier.verify_bundle(inc_unsigned, require_signature=True)
    assert res_unsig.overall_status == "UNSIGNED"
    assert res_unsig.signature_status == "UNSIGNED"


def test_encrypted_evidence_plaintext_hashing(test_env):
    """Phase 6K encrypted evidence (SEN_EVID_V1 header) has its plaintext SHA-256 extracted without decryption key."""
    tmpdir = test_env["tmpdir"]
    raw_content = b"CRITICAL_INCIDENT_AUDIO_WAV_DATA_SAMPLE"
    import hashlib
    expected_plaintext_hash = hashlib.sha256(raw_content).hexdigest()

    # Construct Phase 6K container
    # Format: MAGIC (12B) + kid_len (1B) + kid (kid_len B) + nonce_len (1B) + nonce (nonce_len B) + sha256_raw (32B)
    magic = b"SEN_EVID_V1\x00"
    kid = b"master-v1"
    nonce = b"123456789012"
    ciphertext = b"ENCRYPTED_CIPHERTEXT_BYTES"

    header = (
        magic
        + bytes([len(kid)])
        + kid
        + bytes([len(nonce)])
        + nonce
        + bytes.fromhex(expected_plaintext_hash)
    )
    enc_file = tmpdir / "encrypted_sample.bin"
    enc_file.write_bytes(header + ciphertext)

    computed_hash = compute_file_sha256(enc_file)
    assert computed_hash == expected_plaintext_hash


def test_cli_and_standalone_verifier(test_env):
    """Verifies both python -m evidence and scripts/verify_bundle.py execution."""
    repo = test_env["repo"]
    builder = test_env["builder"]
    incident_id = "INC-CLI-TEST-010"
    create_mock_incident(repo, incident_id)

    bundle_dir, _ = builder.build_bundle(incident_id, sign_key="cli_key_999")

    # 1. Test CLI module
    cmd_mod = [
        sys.executable,
        "-m",
        "evidence",
        "verify",
        "--incident",
        incident_id,
        "--bundle-dir",
        str(bundle_dir),
        "--key",
        "cli_key_999",
        "--json",
    ]
    proc_mod = subprocess.run(cmd_mod, capture_output=True, text=True)
    assert proc_mod.returncode == 0
    mod_out = json.loads(proc_mod.stdout)
    assert mod_out["overall_status"] == "VERIFIED"

    # 2. Test Standalone researcher script
    cmd_standalone = [
        sys.executable,
        "scripts/verify_bundle.py",
        "--bundle",
        str(bundle_dir),
        "--key",
        "cli_key_999",
        "--require-signature",
        "--json",
    ]
    proc_standalone = subprocess.run(cmd_standalone, capture_output=True, text=True)
    assert proc_standalone.returncode == 0
    standalone_out = json.loads(proc_standalone.stdout)
    assert standalone_out["status"] == "VERIFIED"
    assert standalone_out["details"]["signature_status"] == "VALID"
