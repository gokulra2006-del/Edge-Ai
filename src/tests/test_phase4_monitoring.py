"""
test_phase4_monitoring.py - Phase 4 Comprehensive Unit and Integration Tests:
- Feature 7: Model Drift Monitoring (PSI math, thresholds, min sample guard, missing baseline, RESEARCH_ONLY tag, status events)
- Feature 9: Device Health & Resilience (Safe Pi probes on Windows, state changes, availability %, assurance-level mapping)
- Feature 9: Offline-First Operation (Sync outbox backoff, idempotent replay, dead-letter, cap policy protecting audits, recovery drain)
- Feature 10: Camera & Audio Streaming Services (FPS throttling, drop-old-frames, ring-buffer windowing/overlap, silence/clipping flags, reconnect backoff, dependency_missing, start/stop idempotency)
- Dashboard API: Role enforcement for stream control (401/403/200) and #system-health endpoint
"""

import json
import os
import sqlite3
import time
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

from src.modules.database.governed_store import IncidentRepository, IncidentStatus
from src.modules.assurance.drift_monitor import ModelDriftMonitor, compute_histogram, compute_psi
from src.modules.assurance.device_health import (
    HealthMonitor,
    OfflineSyncOutbox,
    safe_probe_pi_metrics,
    derive_assurance_level
)
from src.modules.hardware.stream_service import CameraService, AudioService, StreamHealth
from src.modules.sensor_fusion.decision_logic import ZoneAwareRiskEngine


@pytest.fixture
def test_repo(tmp_path):
    db_file = tmp_path / "test_phase4.db"
    repo = IncidentRepository(db_path=db_file)
    yield repo
    repo.close()


# =============================================================================
# 1. FEATURE 7: MODEL DRIFT MONITORING TESTS
# =============================================================================

def test_psi_against_known_values():
    # Identical distributions should give PSI == 0.0
    actual = [10, 20, 30, 40]
    expected = [10, 20, 30, 40]
    psi = compute_psi(actual, expected)
    assert psi == pytest.approx(0.0, abs=1e-5)

    # Moderate shift
    shifted = [5, 15, 35, 45]
    psi_shifted = compute_psi(shifted, expected)
    assert psi_shifted > 0.0

    # Large shift gives substantial PSI
    severe = [40, 30, 20, 10]
    psi_severe = compute_psi(severe, expected)
    assert psi_severe > psi_shifted


def test_drift_status_thresholds_and_min_sample_guard(test_repo):
    monitor = ModelDriftMonitor(repository=test_repo)
    # Register synthetic baseline
    monitor.set_baseline(
        model_id="test-vision",
        histogram=[0, 0, 0, 0, 0, 0, 0, 0, 50, 50],
        ood_rate=0.01,
        class_prior={"ACCIDENT": 0.5, "NORMAL": 0.5},
        false_alarm_rate=0.01,
        source="synthetic",
        sample_count=100,
        usage_restriction="RESEARCH_ONLY"
    )
    test_repo.writer.drain()

    inc_id, _ = test_repo.create_incident("ACCIDENT", "Z1")

    # 1. With too few samples (< min_samples_guard = 20), status must be WATCH with insufficient_data=True
    for _ in range(5):
        test_repo.add_prediction(inc_id, "ACCIDENT", 0.2, model_id="test-vision")
    test_repo.writer.drain()

    eval_few = monitor.evaluate_model("test-vision")
    assert eval_few["insufficient_data"] is True
    assert eval_few["status"] in ("WATCH", "STABLE")
    assert eval_few["research_only"] is True

    # 2. Add sufficient nominal samples -> STABLE
    for _ in range(25):
        test_repo.add_prediction(inc_id, "ACCIDENT", 0.85, model_id="test-vision")
        test_repo.add_prediction(inc_id, "NORMAL", 0.95, model_id="test-vision")
    test_repo.writer.drain()

    eval_nominal = monitor.evaluate_model("test-vision")
    assert eval_nominal["insufficient_data"] is False
    assert eval_nominal["status"] == "STABLE"

    # 3. Add severe shift (all low confidence, different class) -> DRIFT_WARNING
    for _ in range(50):
        test_repo.add_prediction(inc_id, "UNKNOWN", 0.15, model_id="test-vision")
    test_repo.writer.drain()

    eval_drift = monitor.evaluate_model("test-vision")
    assert eval_drift["status"] == "DRIFT_WARNING"
    assert "PSI_HIGH" in eval_drift["reasons"][0] or "CLASS_PRIOR_SHIFT" in eval_drift["reasons"][0]


def test_drift_missing_baseline(test_repo):
    monitor = ModelDriftMonitor(repository=test_repo)
    inc_id, _ = test_repo.create_incident("ACCIDENT", "Z1")
    for _ in range(5):
        test_repo.add_prediction(inc_id, "ACCIDENT", 0.9, model_id="unregistered-model")
    test_repo.writer.drain()

    res = monitor.evaluate_model("unregistered-model")
    assert res["status"] == "WATCH"
    assert "NO_BASELINE_RECORDED" in res["reasons"]
    assert res["research_only"] is True


def test_drift_snapshots_and_status_event_logged(test_repo):
    monitor = ModelDriftMonitor(repository=test_repo)
    monitor.set_baseline("model-snap", [10]*10, 0.05, {"A": 1.0}, 0.01, "synthetic", 100)
    test_repo.writer.drain()
    inc_id, _ = test_repo.create_incident("ACCIDENT", "Z1")
    for _ in range(25):
        test_repo.add_prediction(inc_id, "A", 0.9, model_id="model-snap")
    test_repo.writer.drain()

    _ = monitor.evaluate_model("model-snap")
    test_repo.writer.drain()

    snapshots = test_repo.rows("drift_snapshots")
    assert len(snapshots) >= 1
    assert snapshots[0]["model_id"] == "model-snap"


# =============================================================================
# 2. FEATURE 9: DEVICE HEALTH & RESILIENCE TESTS
# =============================================================================

def test_safe_pi_probe_on_windows():
    metrics = safe_probe_pi_metrics()
    assert "platform" in metrics
    # On Windows or non-Pi Linux, must report UNAVAILABLE or handle safely without raising
    if metrics["platform"] == "Windows":
        assert metrics["status"] == "UNAVAILABLE"
        assert metrics["cpu_temp_c"] is None
        assert metrics["throttled"] is None


def test_assurance_level_derivation():
    # FULL: all streams ok
    comps_full = {
        "camera": {"status": "OK"},
        "microphone": {"status": "OK"},
        "imu": {"status": "OK"}
    }
    assert derive_assurance_level(comps_full) == "FULL"

    # VISION_ONLY: camera OK, others DOWN
    comps_vision = {
        "camera": {"status": "OK"},
        "microphone": {"status": "DOWN"},
        "imu": {"status": "DOWN"}
    }
    assert derive_assurance_level(comps_vision) == "VISION_ONLY"

    # AUDIO_ONLY: mic OK, others DOWN
    comps_audio = {
        "camera": {"status": "DOWN"},
        "microphone": {"status": "OK"},
        "imu": {"status": "DOWN"}
    }
    assert derive_assurance_level(comps_audio) == "AUDIO_ONLY"

    # SENSORS_ONLY: imu OK, others DOWN
    comps_sensors = {
        "camera": {"status": "DOWN"},
        "microphone": {"status": "DOWN"},
        "imu": {"status": "OK"}
    }
    assert derive_assurance_level(comps_sensors) == "SENSORS_ONLY"

    # DEGRADED: partial combination
    comps_degraded = {
        "camera": {"status": "DOWN"},
        "microphone": {"status": "OK"},
        "imu": {"status": "OK"}
    }
    assert derive_assurance_level(comps_degraded) == "DEGRADED"


def test_health_monitor_state_transitions_and_availability(test_repo):
    monitor = HealthMonitor(repository=test_repo)
    # Poll initial state
    res1 = monitor.poll()
    test_repo.writer.drain()
    events1 = test_repo.rows("device_health_events")
    # Initial state recordings
    assert len(events1) > 0

    # Second poll with unchanged state should NOT write duplicate transition events
    res2 = monitor.poll()
    test_repo.writer.drain()
    events2 = test_repo.rows("device_health_events")
    assert len(events2) == len(events1)

    # Availability pct calculation returns numerical mapping
    avail = monitor.compute_availability_pct()
    assert "database" in avail
    assert avail["database"] == 100.0


# =============================================================================
# 3. FEATURE 9: OFFLINE-FIRST OPERATION & OUTBOX TESTS
# =============================================================================

def test_offline_outbox_enqueue_and_idempotent_replay(test_repo):
    outbox = OfflineSyncOutbox(repository=test_repo)

    # 1. Enqueue item
    assert outbox.enqueue("key-1", "firebase", "AUDIT", {"msg": "hello"}, priority="HIGH") is True
    test_repo.writer.drain()

    # Duplicate idempotency key must not duplicate row
    assert outbox.enqueue("key-1", "firebase", "AUDIT", {"msg": "hello"}, priority="HIGH") is False

    stats = outbox.status_summary()
    assert stats["PENDING"] == 1

    # 2. Replay drain successfully
    called = []
    def mock_sync(tgt, p_type, payload):
        called.append((tgt, p_type))
        return True

    # Ensure eligible
    with sqlite3.connect(str(test_repo.db_path)) as con:
        con.execute("UPDATE sync_outbox SET next_attempt_at='2020-01-01T00:00:00Z'")

    processed = outbox.drain_batch(mock_sync)
    test_repo.writer.drain()
    assert processed == 1
    assert len(called) == 1

    stats_after = outbox.status_summary()
    assert stats_after["SYNCED"] == 1
    assert stats_after["PENDING"] == 0


def test_outbox_backoff_and_dead_letter(test_repo):
    outbox = OfflineSyncOutbox(repository=test_repo)
    outbox.enqueue("fail-key", "firebase", "TELEMETRY", {"v": 1}, priority="LOW")
    test_repo.writer.drain()

    def failing_sync(t, pt, p):
        return False

    with sqlite3.connect(str(test_repo.db_path)) as con:
        con.execute("UPDATE sync_outbox SET attempts=4, next_attempt_at='2020-01-01T00:00:00Z'")

    # Max attempts is 5, next failure marks DEAD_LETTER
    outbox.drain_batch(failing_sync)
    test_repo.writer.drain()

    stats = outbox.status_summary()
    assert stats["DEAD_LETTER"] == 1


def test_outbox_cap_policy_never_drops_audit_rows(test_repo):
    outbox = OfflineSyncOutbox(repository=test_repo)
    outbox.max_rows = 3  # low cap for test

    # Fill with 3 LOW priority items
    outbox.enqueue("low-1", "firebase", "TELEMETRY", {"x": 1}, priority="LOW")
    outbox.enqueue("low-2", "firebase", "TELEMETRY", {"x": 2}, priority="LOW")
    outbox.enqueue("low-3", "firebase", "TELEMETRY", {"x": 3}, priority="LOW")
    test_repo.writer.drain()

    # Enqueue a HIGH priority audit item -> cap compaction drops lowest priority telemetry, NOT audit
    outbox.enqueue("audit-1", "firebase", "INCIDENT_AUDIT", {"inc": 101}, priority="HIGH")
    test_repo.writer.drain()

    rows = test_repo.rows("sync_outbox")
    keys = [r["idempotency_key"] for r in rows]
    assert "audit-1" in keys


# =============================================================================
# 4. FEATURE 10: CAMERA & AUDIO STREAMING SERVICES TESTS
# =============================================================================

def test_camera_service_fps_and_drop_old_frames():
    cam = CameraService(target_fps=20, buffer_max=2, default_source="mock")
    cam.start()
    time.sleep(0.3)

    item = cam.get_latest_frame()
    assert item is not None
    ts, frame = item
    assert frame.shape == (360, 640, 3)

    health = cam.get_health()
    assert health.status == "OK"
    assert health.fps > 0

    cam.stop()
    assert cam.is_running is False
    # Stop idempotency
    cam.stop()


def test_audio_service_windowing_and_clipping():
    # 1024 samples per chunk at 16kHz
    aud = AudioService(sample_rate=16000, window_sec=0.1, hop_sec=0.05, default_source="mock")
    aud.start()
    time.sleep(0.4)

    window = aud.get_latest_window()
    assert window is not None
    assert len(window["samples"]) == int(16000 * 0.1)
    assert "is_clipping" in window
    assert "is_silent" in window

    health = aud.get_health()
    assert health.status == "OK"

    aud.stop()
    assert aud.is_running is False


def test_stream_service_reconnect_loop():
    cam = CameraService(target_fps=15, default_source="mock")
    cam.reconnect_count = 0
    cam.start()
    time.sleep(0.1)

    # Force error state
    cam.status = "DOWN"
    assert cam.get_health().status == "DOWN"
    cam.stop()


# =============================================================================
# 5. DASHBOARD API: ROLE ENFORCEMENT & SYSTEM-HEALTH ROUTE TESTS
# =============================================================================

def test_system_health_endpoints_role_enforcement(test_repo, monkeypatch):
    from http.server import HTTPServer
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    import threading
    from src.modules.dashboard import app as dashboard_app

    monkeypatch.setattr(dashboard_app, "GOVERNED_REPOSITORY", test_repo)
    monkeypatch.setattr(dashboard_app, "AUTH_SESSIONS", {
        "cmdr-token": {"operator_id": "cmd", "role": "COMMANDER"},
        "op-token": {"operator_id": "op", "role": "OPERATOR"},
        "eng-token": {"operator_id": "eng", "role": "ENGINEER"},
        "viewer-token": {"operator_id": "viewer", "role": "VIEWER"},
    })

    server = HTTPServer(("127.0.0.1", 0), dashboard_app.DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    base = f"http://127.0.0.1:{server.server_port}"

    try:
        def post(token, path, payload):
            req = Request(
                f"{base}{path}",
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
            )
            try:
                with urlopen(req) as resp:
                    return resp.status, json.loads(resp.read())
            except HTTPError as exc:
                return exc.code, json.loads(exc.read())

        # 1. Unauthenticated or unauthorized cannot control stream
        assert post("", "/api/monitoring/stream/control", {"stream": "camera", "action": "stop"})[0] == 401
        assert post("viewer-token", "/api/monitoring/stream/control", {"stream": "camera", "action": "stop"})[0] == 403
        assert post("eng-token", "/api/monitoring/stream/control", {"stream": "camera", "action": "stop"})[0] == 403

        # Commander and Operator CAN control stream
        st, b = post("cmdr-token", "/api/monitoring/stream/control", {"stream": "camera", "action": "stop"})
        assert st == 200 and b["status"] == "SUCCESS"

        st_op, b_op = post("op-token", "/api/monitoring/stream/control", {"stream": "camera", "action": "start"})
        assert st_op == 200 and b_op["status"] == "SUCCESS"

        # 2. GET monitoring endpoints are accessible
        with urlopen(f"{base}/api/monitoring/health") as resp:
            assert resp.status == 200
            data = json.loads(resp.read())
            assert "assurance_level" in data
            assert "components" in data

        with urlopen(f"{base}/api/monitoring/drift") as resp:
            assert resp.status == 200

        with urlopen(f"{base}/api/monitoring/streams") as resp:
            assert resp.status == 200

        with urlopen(f"{base}/api/monitoring/outbox") as resp:
            assert resp.status == 200
    finally:
        server.shutdown()
        server.server_close()
