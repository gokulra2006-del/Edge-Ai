"""
Comprehensive Tests for Stage I1: Backend Foundation & Edge Device Ingestion.
=============================================================================
Tests:
1. Telemetry Schema 1.0 validation (valid and invalid payloads)
2. Device registration and constant-time token verification (hashing)
3. Idempotent telemetry ingestion (duplicate event_id ignored)
4. Sequence gap and boot_id restart detection
5. Edge agent client packet assembly
6. Device REST endpoints & role permissions
7. Zero GPIO26 / Physical pin 37 allocation invariant test
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.config.hardware_config import HARDWARE_CONFIG
from src.modules.database.governed_store import IncidentRepository
from src.modules.edge_agent.telemetry_schema import TelemetryValidator
from src.modules.edge_agent.device_registry import DeviceRegistry, hash_device_token
from src.modules.edge_agent.agent_client import EdgeAgentClient
from src.modules.security.permission_matrix import check_endpoint_permission


@pytest.fixture
def test_repo(tmp_path: Path):
    db_path = tmp_path / "test_stage_i1.db"
    repo = IncidentRepository(db_path=db_path)
    yield repo
    repo.close()


def test_hardware_pin_safety_invariants():
    """Verify hardware pin map has no conflicts and GPIO 26 / Physical Pin 37 is strictly unused."""
    errors = HARDWARE_CONFIG.validate_pin_assignments()
    assert errors == [], f"Hardware pin validation failed: {errors}"

    for name, pin in HARDWARE_CONFIG.PINS.items():
        assert pin.bcm != 26, f"Prohibited GPIO 26 allocated to '{name}'!"
        assert pin.physical != 37, f"Prohibited Physical Pin 37 allocated to '{name}'!"


def test_telemetry_schema_validation():
    """Verify strict validation against Schema 1.0."""
    client = EdgeAgentClient(device_id="rpi4-node-b", data_source="SIMULATED")
    valid_packet = client.build_telemetry_packet()

    # 1. Valid packet passes
    res = TelemetryValidator.validate(valid_packet)
    assert res.is_valid, f"Expected valid packet: {res.errors}"

    # 2. Reject unsupported schema major version
    bad_ver = dict(valid_packet, schema_version="2.0")
    res2 = TelemetryValidator.validate(bad_ver)
    assert not res2.is_valid
    assert any("major version" in e for e in res2.errors)

    # 3. Reject invalid clock status
    bad_clock = dict(valid_packet, clock_status="UNKNOWN")
    res3 = TelemetryValidator.validate(bad_clock)
    assert not res3.is_valid
    assert any("clock_status" in e for e in res3.errors)

    # 4. Reject negative sequence
    bad_seq = dict(valid_packet, sequence=-5)
    res4 = TelemetryValidator.validate(bad_seq)
    assert not res4.is_valid
    assert any("sequence" in e for e in res4.errors)


def test_device_registration_and_token_auth(test_repo):
    """Verify device registration, SHA-256 token hashing, and authentication."""
    registry = DeviceRegistry(repository=test_repo)

    # Register device with secret token
    reg = registry.register_device(
        device_id="rpi4-node-b",
        name="Main Pi 4 Node",
        token="super-secret-pi-token-2026",
        data_source="REAL_HARDWARE",
    )
    assert reg["device_id"] == "rpi4-node-b"

    # Token verification
    assert registry.verify_device_token("rpi4-node-b", "super-secret-pi-token-2026")
    assert not registry.verify_device_token("rpi4-node-b", "wrong-token")
    assert not registry.verify_device_token("nonexistent-device", "any-token")


def test_idempotent_ingestion_and_restart_gap_detection(test_repo):
    """Verify deduplication, sequence gap detection, and boot_id restarts."""
    registry = DeviceRegistry(repository=test_repo)
    registry.register_device("rpi4-node-b", "Test Node", "token-1")

    client = EdgeAgentClient(device_id="rpi4-node-b", data_source="SIMULATED")

    # Packet 1 (Seq 1)
    p1 = client.build_telemetry_packet()
    res1 = registry.ingest_telemetry(p1)
    assert res1["status"] == "INGESTED"
    assert res1["sequence"] == 1
    assert not res1["is_restart"]
    assert not res1["gap_detected"]

    # Ingesting exact same packet again -> DUPLICATE_IGNORED
    res_dup = registry.ingest_telemetry(p1)
    assert res_dup["status"] == "DUPLICATE_IGNORED"
    assert res_dup["is_duplicate"]

    # Packet 2 with sequence jump (Seq 5 -> gap of [2, 3, 4])
    client.sequence = 4
    p_jump = client.build_telemetry_packet()
    assert p_jump["sequence"] == 5
    res_jump = registry.ingest_telemetry(p_jump)
    assert res_jump["status"] == "INGESTED"
    assert res_jump["gap_detected"]
    assert res_jump["missing_sequences"] == [2, 3, 4]

    # Packet 3 from new boot_id -> RESTART DETECTED
    client_reboot = EdgeAgentClient(device_id="rpi4-node-b", data_source="SIMULATED")
    p_reboot = client_reboot.build_telemetry_packet()
    res_reboot = registry.ingest_telemetry(p_reboot)
    assert res_reboot["status"] == "INGESTED"
    assert res_reboot["is_restart"]


def test_telemetry_query_and_history(test_repo):
    """Verify retrieving latest telemetry and paginated history."""
    registry = DeviceRegistry(repository=test_repo)
    registry.register_device("rpi4-node-b", "Test Node", "token-1")

    client = EdgeAgentClient(device_id="rpi4-node-b", data_source="SIMULATED")
    for _ in range(5):
        pkt = client.build_telemetry_packet()
        registry.ingest_telemetry(pkt)

    latest = registry.get_latest_telemetry("rpi4-node-b")
    assert latest is not None
    assert latest["sequence"] == 5

    history = registry.get_telemetry_history("rpi4-node-b", limit=3, offset=0)
    assert len(history) == 3
    assert history[0]["sequence"] == 5
    assert history[1]["sequence"] == 4
    assert history[2]["sequence"] == 3


def test_device_api_role_permissions():
    """Verify role permissions on newly added device endpoints."""
    # GET /api/devices is allowed for ALL_ROLES
    ok, st, _ = check_endpoint_permission("/api/devices", "GET", "VIEWER")
    assert ok and st == 200

    # POST /api/devices/{id}/commands requires COMMANDER or OPERATOR
    ok_cmd, st_cmd, _ = check_endpoint_permission("/api/devices/rpi4-node-b/commands", "POST", "OPERATOR")
    assert ok_cmd and st_cmd == 200

    ok_cmd_fail, st_cmd_fail, _ = check_endpoint_permission("/api/devices/rpi4-node-b/commands", "POST", "VIEWER")
    assert not ok_cmd_fail and st_cmd_fail == 403

    # Ingestion POST /api/devices/{id}/telemetry allows unauthenticated (token in header)
    ok_ingest, st_ingest, _ = check_endpoint_permission("/api/devices/rpi4-node-b/telemetry", "POST", None)
    assert ok_ingest and st_ingest == 200
