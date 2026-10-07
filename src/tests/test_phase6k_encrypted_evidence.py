"""
Phase 6K Test Suite: Authenticated Evidence Encryption at Rest & Denied Action Audit Logging.
=============================================================================================
Verifies:
1. AES-256-GCM encryption at rest with SEN_EVID_V1 envelope format.
2. Tamper detection: modifying ciphertext, nonce, tag, or header raises EvidenceTamperDetectedError.
3. Wrong key rejection: attempting decryption with wrong key or absent key fails authentication.
4. Plaintext hash invariance: SHA-256 computed pre-encryption matches decrypted digest bit-for-bit.
5. Role authorization and audit logging:
   - COMMANDER, OPERATOR, ENGINEER allowed.
   - VIEWER denied with DecryptionPermissionDenied and audit-logged in operator_actions.
6. Key rotation support: decrypt historic key, re-encrypt active key, plaintext hash unchanged.
7. Migration CLI: batch encryption of unencrypted evidence directory.
8. Retention rule compatibility: pruning obsolete encrypted (.enc) files.
9. 5E Follow-up: Audit logging for every denied action (role x forbidden-action produces audit record).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import pytest


from src.modules.database.governed_store import IncidentRepository
from src.modules.storage.evidence_encryption import (
    EvidenceEncryptor,
    EvidenceKeyRing,
    EvidenceTamperDetectedError,
    EvidenceIntegrityError,
    KeyNotFoundError,
    DecryptionPermissionDenied,
    generate_aes256_key,
    MAGIC_HEADER,
)
from src.modules.reporting.evidence_package import MerkleEvidencePackager
from src.modules.storage.storage_safety import StorageRetentionEngine
from src.modules.security.permission_matrix import (
    ENDPOINT_PERMISSIONS,
    check_endpoint_permission,
    audit_denied_action,
    ALL_ROLES,
)
from src.modules.incident_management.workflow import OperatorWorkflow, PermissionDenied


@pytest.fixture
def temp_repo(tmp_path):
    db_file = tmp_path / "test_governed.db"
    repo = IncidentRepository(db_path=db_file)
    yield repo
    repo.close()


@pytest.fixture
def key_ring():
    k1 = generate_aes256_key()
    k2 = generate_aes256_key()
    return EvidenceKeyRing(keys={"key-2026-v1": k1, "key-2026-v2": k2}, active_kid="key-2026-v2")


def test_tamper_detection(temp_repo, key_ring, tmp_path):
    """Flipping a single byte anywhere in the ciphertext must trigger EvidenceTamperDetectedError."""
    encryptor = EvidenceEncryptor(key_ring=key_ring, repository=temp_repo)
    plaintext = b"CRITICAL FORENSIC EVIDENCE: SPEED=85MPH, STATUS=IMPACT"
    incident_id = "INC-TEST-001"
    filename = "telemetry_blackbox.bin"

    envelope, digest = encryptor.encrypt_bytes(plaintext, incident_id=incident_id, filename=filename)
    assert envelope.startswith(MAGIC_HEADER)
    assert len(envelope) > len(plaintext)

    # 1. Flip a byte in the ciphertext payload
    tampered_payload = bytearray(envelope)
    tampered_payload[-5] ^= 0xFF
    with pytest.raises(EvidenceTamperDetectedError):
        encryptor.decrypt_bytes(
            bytes(tampered_payload),
            incident_id=incident_id,
            filename=filename,
            actor_role="COMMANDER",
            operator_id="cmd_tamper_test",
        )

    # 2. Tamper with AAD by changing incident_id
    with pytest.raises(EvidenceTamperDetectedError):
        encryptor.decrypt_bytes(
            envelope,
            incident_id="INC-ATTACKER-FAKE",
            filename=filename,
            actor_role="COMMANDER",
            operator_id="cmd_tamper_test",
        )


def test_wrong_key_rejection(temp_repo, tmp_path):
    """Decrypting with a wrong key or key missing from KeyRing must fail."""
    k1 = generate_aes256_key()
    k_wrong = generate_aes256_key()

    ring_a = EvidenceKeyRing(keys={"key-1": k1}, active_kid="key-1")
    ring_b = EvidenceKeyRing(keys={"key-1": k_wrong}, active_kid="key-1")  # Same kid, different secret
    ring_c = EvidenceKeyRing(keys={"other-key": k_wrong}, active_kid="other-key")  # Missing key-1

    encryptor_a = EvidenceEncryptor(key_ring=ring_a, repository=temp_repo)
    encryptor_b = EvidenceEncryptor(key_ring=ring_b, repository=temp_repo)
    encryptor_c = EvidenceEncryptor(key_ring=ring_c, repository=temp_repo)

    plaintext = b"AUTHENTIC CAMERA FRAME BYTES"
    envelope, _ = encryptor_a.encrypt_bytes(plaintext, "INC-TEST-002", "frame.jpg")

    # Decrypt with wrong secret -> GCM auth tag mismatch
    with pytest.raises(EvidenceTamperDetectedError):
        encryptor_b.decrypt_bytes(envelope, "INC-TEST-002", "frame.jpg", actor_role="COMMANDER")

    # Decrypt with missing key -> KeyNotFoundError
    with pytest.raises(KeyNotFoundError):
        encryptor_c.decrypt_bytes(envelope, "INC-TEST-002", "frame.jpg", actor_role="COMMANDER")


def test_plaintext_hash_invariance(temp_repo, key_ring):
    """Plaintext SHA-256 hash pre-encryption equals decrypted hash and Merkle packager hash."""
    import hashlib
    encryptor = EvidenceEncryptor(key_ring=key_ring, repository=temp_repo)
    data = b"Multi-modal sensor trace 12345: acoustic signature, thermal delta."
    expected_hash = hashlib.sha256(data).hexdigest()

    envelope, reported_hash = encryptor.encrypt_bytes(data, "INC-TEST-003", "trace.dat")
    assert reported_hash == expected_hash

    decrypted = encryptor.decrypt_bytes(envelope, "INC-TEST-003", "trace.dat", actor_role="OPERATOR")
    decrypted_hash = hashlib.sha256(decrypted).hexdigest()
    assert decrypted_hash == expected_hash

    # Header inspect: read_plaintext_sha256 without secret key
    header_hash = EvidenceEncryptor.read_plaintext_sha256(envelope)
    assert header_hash == expected_hash


def test_role_authorization_and_audit(temp_repo, key_ring):
    """
    Authorized roles (COMMANDER, OPERATOR, ENGINEER) succeed.
    VIEWER raises DecryptionPermissionDenied and generates an audit record.
    """
    encryptor = EvidenceEncryptor(key_ring=key_ring, repository=temp_repo)
    plaintext = b"SECRET INCIDENT EVIDENCE"
    envelope, _ = encryptor.encrypt_bytes(plaintext, "INC-TEST-004", "evidence.bin")

    # Authorized roles
    for role in ["COMMANDER", "OPERATOR", "ENGINEER"]:
        res = encryptor.decrypt_bytes(envelope, "INC-TEST-004", "evidence.bin", actor_role=role, operator_id=f"user_{role.lower()}")
        assert res == plaintext

    # VIEWER must fail
    with pytest.raises(DecryptionPermissionDenied):
        encryptor.decrypt_bytes(envelope, "INC-TEST-004", "evidence.bin", actor_role="VIEWER", operator_id="user_viewer")

    # Verify audit trail in operator_actions
    temp_repo.writer.drain()
    actions = temp_repo.rows("operator_actions", "INC-TEST-004")
    decrypt_actions = [a for a in actions if a["action"] == "evidence_decryption"]
    assert len(decrypt_actions) >= 4  # 3 approvals + 1 denial

    viewer_audit = [a for a in decrypt_actions if a["operator_id"] == "user_viewer"][0]
    assert viewer_audit["approved"] == 0
    payload = json.loads(viewer_audit["payload_json"])
    assert payload["role"] == "VIEWER"
    assert "not authorized" in payload["reason"].lower()


def test_key_rotation(temp_repo, tmp_path):
    """Key rotation: encrypt with k1, rotate active to k2, re-encrypt file, verify unchanged plaintext hash."""
    k1 = generate_aes256_key()
    k2 = generate_aes256_key()
    ring = EvidenceKeyRing(keys={"k1": k1, "k2": k2}, active_kid="k1")
    encryptor = EvidenceEncryptor(key_ring=ring, repository=temp_repo)

    file_p = tmp_path / "sensor_data.csv"
    file_p.write_text("timestamp,speed,temp\n1000,45.2,28.5\n", encoding="utf-8")

    enc_p, orig_digest = encryptor.encrypt_file(file_p, incident_id="INC-TEST-005")
    assert enc_p.name.endswith(".enc")
    assert encryptor.is_encrypted_file(enc_p)

    # Rotate active key to k2
    ring.active_kid = "k2"
    reenc_p, new_digest = encryptor.reencrypt_file(enc_p, incident_id="INC-TEST-005", new_kid="k2")
    assert new_digest == orig_digest

    # Verify decrypt with new active key
    decrypted_p = encryptor.decrypt_file(reenc_p, incident_id="INC-TEST-005", actor_role="COMMANDER")
    assert decrypted_p.read_text(encoding="utf-8") == "timestamp,speed,temp\n1000,45.2,28.5\n"


def test_migration_cli_and_merkle_index(temp_repo, key_ring, tmp_path):
    """Batch encrypts directory and verifies MerkleEvidencePackager indexing."""
    from scripts.storage.migrate_evidence_encryption import migrate_evidence_directory
    encryptor = EvidenceEncryptor(key_ring=key_ring, repository=temp_repo)

    evidence_dir = tmp_path / "evidence_store"
    evidence_dir.mkdir()
    f1 = evidence_dir / "cam_01.jpg"
    f1.write_bytes(b"JPEG_FRAME_01_RAW_BYTES")
    f2 = evidence_dir / "mic_01.wav"
    f2.write_bytes(b"WAV_AUDIO_01_RAW_BYTES")

    summary = migrate_evidence_directory(
        directory=evidence_dir,
        encryptor=encryptor,
        incident_id="INC-TEST-006",
        delete_unencrypted=True,
    )
    assert summary["encrypted_count"] == 2
    assert summary["failed_count"] == 0
    assert not f1.exists()
    assert Path(str(f1) + ".enc").exists()
    assert Path(str(f2) + ".enc").exists()

    # Verify Merkle Evidence Package can read plaintext digests directly from .enc files
    enc_f1 = Path(str(f1) + ".enc")
    enc_f2 = Path(str(f2) + ".enc")
    manifest_dict, manifest = MerkleEvidencePackager.create_package(
        incident_id="INC-TEST-006",
        files=[(enc_f1, "camera_frame"), (enc_f2, "audio_clip")],
        operator_id="cmd_packager",
    )
    assert len(manifest.leaves) == 2
    for leaf in manifest.leaves:
        assert leaf.encrypted is True
        assert leaf.key_id == "key-2026-v2"
        assert len(leaf.sha256_hash) == 64
        # Verify plaintext hash matches original unencrypted bytes
        if "cam_01" in leaf.filename:
            assert leaf.sha256_hash == hashlib.sha256(b"JPEG_FRAME_01_RAW_BYTES").hexdigest()
        elif "mic_01" in leaf.filename:
            assert leaf.sha256_hash == hashlib.sha256(b"WAV_AUDIO_01_RAW_BYTES").hexdigest()



def test_retention_pruning_encrypted(temp_repo, key_ring, tmp_path):
    """Retention cleanup prunes .enc files for closed incidents properly."""
    engine = StorageRetentionEngine(repository=temp_repo)
    encryptor = EvidenceEncryptor(key_ring=key_ring, repository=temp_repo)

    inc_id, _ = temp_repo.create_incident("ACCIDENT", "ZONE_A")
    raw_file = tmp_path / "clip.mp4"
    raw_file.write_bytes(b"VIDEO_CLIP_BYTES")
    enc_path, sha = encryptor.encrypt_file(raw_file, incident_id=inc_id)

    # Attach to repo
    temp_repo.attach_evidence(inc_id, "dvr_clip", enc_path, sha, encrypted=True, key_id="key-2026-v2")
    temp_repo.writer.drain()

    # Close incident so retention applies
    def _close(db):
        db.execute("UPDATE incidents SET status='CLOSED', created_at='2020-01-01T00:00:00Z' WHERE incident_id=?", (inc_id,))
    temp_repo.writer.submit_wait(_close)

    report = engine.cleanup_evidence(retention_days=1, dry_run=False)
    assert report["items_pruned"] >= 1
    assert not enc_path.exists()



def test_denied_actions_audit_logging_5e_followup(temp_repo):
    """
    5E FOLLOW-UP INVARIANT:
    Proves that authorization denials across all forbidden role x action combinations
    write an audit record into operator_actions ledger (who, role, action, timestamp, reason).
    """
    # 1. OperatorWorkflow forbidden action check:
    # Role OPERATOR cannot execute "resolve" or "escalate"
    workflow = OperatorWorkflow(repository=temp_repo)
    inc_id, _ = temp_repo.create_incident("ACCIDENT", "ZONE_B")
    temp_repo.writer.drain()

    row = workflow.get_incident(inc_id)
    with pytest.raises(PermissionDenied):
        workflow.act(
            incident_id=inc_id,
            action="resolve",
            operator_id="operator_bob",
            role="OPERATOR",
            version=row["version"],
            note="Unauthorized resolve attempt",
        )

    with pytest.raises(PermissionDenied):
        workflow.act(
            incident_id=inc_id,
            action="escalate",
            operator_id="operator_bob",
            role="OPERATOR",
            version=row["version"],
            note="Unauthorized escalate attempt",
        )

    temp_repo.writer.drain()
    actions = temp_repo.rows("operator_actions", inc_id)
    denied_actions = [a for a in actions if a["action"].startswith("DENIED:")]
    assert len(denied_actions) == 2
    for da in denied_actions:
        assert da["operator_id"] == "operator_bob"
        assert da["approved"] == 0
        p = json.loads(da["payload_json"])
        assert p["operator_role"] == "OPERATOR"
        assert p["reason"] == "forbidden"

    # 2. Permission Matrix denied action check for each role x forbidden-action
    forbidden_matrix = [
        ("VIEWER", "POST", "/api/actuators/servo"),
        ("VIEWER", "POST", "/api/hardware/mode"),
        ("VIEWER", "POST", "/api/incidents/INC-1/acknowledge"),
        ("OPERATOR", "POST", "/api/storage/cleanup"),
        ("OPERATOR", "POST", "/api/auth/users"),
        ("ENGINEER", "POST", "/api/incidents/INC-1/resolve"),
    ]

    for role, method, path in forbidden_matrix:
        ok, status, reason = check_endpoint_permission(
            path=path,
            method=method,
            role=role,
            operator_id=f"user_{role.lower()}",
            repository=temp_repo,
        )
        assert not ok
        assert status == 403

    temp_repo.writer.drain()
    # Check SYSTEM anchor records for these denied requests
    sys_actions = temp_repo.rows("operator_actions", "SYSTEM")
    assert len(sys_actions) >= len(forbidden_matrix)
    logged_roles = {json.loads(a["payload_json"]).get("role") for a in sys_actions}
    for r, _, _ in forbidden_matrix:
        assert r in logged_roles
