"""Feature 9: Device health monitoring, safe platform probes, and offline-first outbox."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import random
import shutil
import sqlite3
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.request

from src.config.governance_config import load_governance_config
from src.modules.database.governed_store import IncidentRepository, utc_now
from src.modules.hardware.hardware_hub import HARDWARE_HUB
from src.modules.logging.logger import LOGGER

ROOT_DIR = Path(__file__).resolve().parents[3]


def safe_probe_pi_metrics() -> Dict[str, Any]:
    """
    Safely probes Raspberry Pi CPU temperature and throttling flags.
    On Windows / non-Pi systems, reports UNAVAILABLE without raising.
    """
    metrics = {
        "cpu_temp_c": None,
        "throttled": None,
        "status": "UNAVAILABLE",
        "platform": platform.system(),
    }

    # Attempt to read Pi sysfs thermal zone
    thermal_path = Path("/sys/class/thermal/thermal_zone0/temp")
    if thermal_path.exists():
        try:
            raw = thermal_path.read_text().strip()
            metrics["cpu_temp_c"] = round(float(raw) / 1000.0, 1)
            metrics["status"] = "OK"
        except Exception:
            pass

    # Attempt to query vcgencmd for throttling
    try:
        import subprocess
        res = subprocess.run(["vcgencmd", "get_throttled"], capture_value=True, text=True, timeout=1)
        if res.returncode == 0:
            metrics["throttled"] = res.stdout.strip()
            metrics["status"] = "OK"
    except Exception:
        pass

    return metrics


def derive_assurance_level(components: Dict[str, Dict[str, Any]]) -> str:
    """
    Derives coverage level:
    - FULL: Camera, Mic, and Sensors all OK/DEGRADED (available)
    - VISION_ONLY: Mic DOWN, Sensors DOWN, Camera OK
    - AUDIO_ONLY: Camera DOWN, Sensors DOWN, Mic OK
    - SENSORS_ONLY: Camera DOWN, Mic DOWN, Sensors OK
    - DEGRADED: Partial combination with at least one critical stream down
    """
    cam_ok = components.get("camera", {}).get("status") in ("OK", "DEGRADED")
    mic_ok = components.get("microphone", {}).get("status") in ("OK", "DEGRADED")
    sensors_ok = (
        components.get("imu", {}).get("status") in ("OK", "DEGRADED") or
        components.get("gas", {}).get("status") in ("OK", "DEGRADED") or
        components.get("climate", {}).get("status") in ("OK", "DEGRADED")
    )

    if cam_ok and mic_ok and sensors_ok:
        return "FULL"
    if cam_ok and not mic_ok and not sensors_ok:
        return "VISION_ONLY"
    if mic_ok and not cam_ok and not sensors_ok:
        return "AUDIO_ONLY"
    if sensors_ok and not cam_ok and not mic_ok:
        return "SENSORS_ONLY"
    return "DEGRADED"


class HealthMonitor:
    """
    Polls subsystem health, records state transitions in device_health_events,
    and computes assurance levels (FULL, VISION_ONLY, AUDIO_ONLY, SENSORS_ONLY, DEGRADED).
    """

    def __init__(self, repository: IncidentRepository, config: Optional[Dict[str, Any]] = None):
        self.repository = repository
        self.config = config or self._load_config()
        self.cfg = self.config.get("monitoring", {}).get("health", {})
        storage_thresh = self.config.get("storage", {}).get("thresholds", {})
        self.warn_storage = int(storage_thresh.get("warning_bytes", self.cfg.get("storage_warning_bytes", 1000000000)))
        self.crit_storage = int(storage_thresh.get("critical_bytes", self.cfg.get("storage_critical_bytes", 250000000)))
        self.writer_depth_warn = int(self.cfg.get("writer_queue_warning_depth", 192))
        self.last_status: Dict[str, str] = {}
        self.last_seen: Dict[str, str] = {}
        self._lock = threading.Lock()

    def _load_config(self) -> Dict[str, Any]:
        cfg_file = Path(__file__).resolve().parents[2] / "config" / "advanced_platform.json"
        try:
            return json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def poll(self) -> Dict[str, Any]:
        """Polls all components and returns state snapshot."""
        now = utc_now()
        components: Dict[str, Dict[str, Any]] = {}

        # 1. Database & Writer queue
        writer_health = self.repository.writer.health()
        qsize = writer_health.get("queued", 0)
        wal_size = 0
        wal_path = Path(str(self.repository.db_path) + "-wal")
        if wal_path.exists():
            wal_size = wal_path.stat().st_size

        if not writer_health.get("healthy"):
            db_status = "DEGRADED"
            db_reason = "WRITER_FAILURES"
            db_msg = "; ".join(writer_health.get("failures", [])[-2:])
        elif qsize >= self.writer_depth_warn:
            db_status = "DEGRADED"
            db_reason = "QUEUE_DEPTH_HIGH"
            db_msg = f"Queue depth: {qsize}"
        else:
            db_status = "OK"
            db_reason = "NOMINAL"
            db_msg = f"Queue size: {qsize}, WAL: {wal_size // 1024} KB"

        components["database"] = {
            "status": db_status, "reason_code": db_reason, "message": db_msg,
            "last_seen": now, "details": {"queue_size": qsize, "wal_bytes": wal_size}
        }

        # 2. Storage
        usage = shutil.disk_usage(self.repository.db_path.parent)
        if usage.free < self.crit_storage:
            st_status, st_reason = "DOWN", "STORAGE_CRITICAL"
            st_msg = f"Free space critically low: {usage.free // 1000000} MB"
        elif usage.free < self.warn_storage:
            st_status, st_reason = "DEGRADED", "STORAGE_WARNING"
            st_msg = f"Free space low: {usage.free // 1000000} MB"
        else:
            st_status, st_reason = "OK", "NOMINAL"
            st_msg = f"{usage.free // 1000000000} GB free"

        components["storage"] = {
            "status": st_status, "reason_code": st_reason, "message": st_msg,
            "last_seen": now, "details": {
                "free_bytes": usage.free,
                "total_bytes": usage.total,
                "warning_threshold_bytes": self.warn_storage,
                "critical_threshold_bytes": self.crit_storage,
                "wal_bytes": wal_size,
            }
        }

        # 3. Hardware sensors & camera/mic via HARDWARE_HUB
        try:
            hw_health = HARDWARE_HUB.get_system_health()
            drivers = hw_health.get("drivers", {})
            for dev_key, dev_pattern in [
                ("camera", "camera"),
                ("microphone", "inmp441"),
                ("imu", "gy87"),
                ("gas", "mq2"),
                ("climate", "dht22"),
                ("gps", "gps")
            ]:
                drv = {}
                for d_name, d_val in drivers.items():
                    if dev_pattern in d_name.lower():
                        drv = d_val
                        break
                d_status = drv.get("status", "OK")
                # Map driver status to health enum: OK / DEGRADED / DOWN / UNKNOWN
                if d_status in ("ONLINE", "OK"):
                    stat = "OK"
                elif d_status in ("DEGRADED", "WARMING_UP", "NO_FIX"):
                    stat = "DEGRADED"
                elif d_status in ("OFFLINE", "DOWN", "ERROR", "NOT_DETECTED"):
                    stat = "DOWN"
                else:
                    stat = "UNKNOWN"

                components[dev_key] = {
                    "status": stat,
                    "reason_code": d_status,
                    "message": f"Driver {dev_key}: {d_status} (Simulated: {drv.get('is_simulated', True)})",
                    "last_seen": now,
                    "details": drv
                }
        except Exception as e:
            LOGGER.error(f"HardwareHub polling note: {e}")

        # 4. Host metrics (Pi-safe)
        pi_info = safe_probe_pi_metrics()
        components["host_platform"] = {
            "status": "OK" if pi_info["status"] != "UNAVAILABLE" else "OK", # host is running
            "reason_code": "PROBE_SUCCESS" if pi_info["status"] == "OK" else "HOST_PROBE_UNAVAILABLE",
            "message": f"System: {pi_info['platform']}, CPU: {pi_info['cpu_temp_c'] or 'N/A'}",
            "last_seen": now,
            "details": pi_info
        }

        # 5. Network / Firebase Reachability
        from src.modules.dashboard.firebase_sync import FIREBASE_SYNC
        fb_configured = FIREBASE_SYNC.is_configured()
        fb_connected = FIREBASE_SYNC.local_cache.get("connected", False)
        if not fb_configured:
            net_stat = "OK"
            net_reason = "LOCAL_MODE"
            net_msg = "Local mode active (Cloud sync optional)"
        elif fb_connected:
            net_stat = "OK"
            net_reason = "CLOUD_CONNECTED"
            net_msg = "Connected to Firebase Realtime Database"
        else:
            net_stat = "DEGRADED"
            net_reason = "CLOUD_UNREACHABLE"
            net_msg = "Firebase cloud unreachable (Offline local operations maintained)"

        components["network"] = {
            "status": net_stat, "reason_code": net_reason, "message": net_msg,
            "last_seen": now, "details": {"configured": fb_configured, "connected": fb_connected}
        }

        # Persist state changes only
        self._record_state_changes(components, now)

        # Derive assurance level
        assurance_level = self.derive_assurance_level(components)

        return {
            "timestamp": now,
            "assurance_level": assurance_level,
            "components": components,
            "availability_pct": self.compute_availability_pct(),
        }

    def _record_state_changes(self, components: Dict[str, Dict[str, Any]], timestamp: str) -> None:
        with self._lock:
            for comp, data in components.items():
                curr_status = data["status"]
                prev_status = self.last_status.get(comp)
                if prev_status != curr_status:
                    self.last_status[comp] = curr_status
                    self.last_seen[comp] = timestamp
                    reason = data.get("reason_code", "UNKNOWN")
                    msg = data.get("message", "")
                    details = json.dumps(data.get("details", {}))
                    self.repository.writer.submit(
                        lambda db, c=comp, ps=prev_status, cs=curr_status, rc=reason, m=msg, dj=details, ts=timestamp: (
                            db.execute(
                                """
                                INSERT INTO device_health_events
                                (timestamp, component, previous_status, current_status, reason_code, message, details_json)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                """,
                                (ts, c, ps, cs, rc, m, dj)
                            )
                        )
                    )

    def derive_assurance_level(self, components: Dict[str, Dict[str, Any]]) -> str:
        return derive_assurance_level(components)

    def compute_availability_pct(self, hours: int = 24) -> Dict[str, float]:
        """Calculates availability percentage per component based on transition events."""
        # Baseline default: 100.0% if no downtime recorded
        rows = self.repository._read(
            "SELECT component, current_status, count(*) as count FROM device_health_events GROUP BY component, current_status"
        )
        avail = {}
        for comp in ["camera", "microphone", "database", "storage", "imu", "gas", "climate", "gps", "network"]:
            comp_rows = [r for r in rows if r["component"] == comp]
            if not comp_rows:
                avail[comp] = 100.0
            else:
                down_events = sum(r["count"] for r in comp_rows if r["current_status"] == "DOWN")
                total_events = sum(r["count"] for r in comp_rows)
                avail[comp] = round(max(0.0, 100.0 - (down_events / total_events * 100.0)), 1)
        return avail


class OfflineSyncOutbox:
    """
    Offline-first sync outbox for background Firebase sync with exponential backoff,
    jitter, dead-letter state, and cap policies that NEVER drop incident/audit rows.
    """

    def __init__(self, repository: IncidentRepository, config: Optional[Dict[str, Any]] = None):
        self.repository = repository
        self.config = config or self._load_config()
        self.cfg = self.config.get("monitoring", {}).get("outbox", {})
        self.max_rows = int(self.cfg.get("max_rows_cap", 500))
        self.max_attempts = int(self.cfg.get("max_attempts", 5))
        self.backoff_base = float(self.cfg.get("backoff_base_seconds", 1.0))
        self.backoff_max = float(self.cfg.get("backoff_max_seconds", 60.0))
        self.jitter_factor = float(self.cfg.get("jitter_factor", 0.2))

    def _load_config(self) -> Dict[str, Any]:
        cfg_file = Path(__file__).resolve().parents[2] / "config" / "advanced_platform.json"
        try:
            return json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def enqueue(
        self,
        idempotency_key: str,
        target: str,
        payload_type: str,
        payload: Dict[str, Any],
        payload_ref: str | None = None,
        priority: str = "NORMAL"
    ) -> bool:
        """
        Enqueues an item for background sync.
        Audits / incidents must have priority='HIGH' or 'AUDIT' so they are NEVER dropped.
        """
        # Check idempotency duplicate
        existing = self.repository._read("SELECT id FROM sync_outbox WHERE idempotency_key=?", (idempotency_key,))
        if existing:
            return False

        self._enforce_cap_policy()
        ts = utc_now()
        payload_str = json.dumps(payload, sort_keys=True)

        return self.repository.writer.submit(
            lambda db: db.execute(
                """
                INSERT OR IGNORE INTO sync_outbox
                (idempotency_key, target, payload_type, payload_ref, payload_json, attempts, next_attempt_at, status, priority, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, 'PENDING', ?, ?, ?)
                """,
                (idempotency_key, target, payload_type, payload_ref, payload_str, ts, priority, ts, ts)
            )
        )

    def _enforce_cap_policy(self) -> None:
        """Drops or compacts only low-priority telemetry when outbox cap is reached."""
        rows = self.repository._read("SELECT count(*) FROM sync_outbox WHERE status='PENDING'")
        count = rows[0][0] if rows else 0
        if count >= self.max_rows:
            # Drop lowest-priority pending rows, NEVER drop AUDIT or HIGH
            self.repository.writer.submit(
                lambda db: db.execute(
                    """
                    DELETE FROM sync_outbox WHERE status='PENDING' AND priority='LOW' AND id IN (
                        SELECT id FROM sync_outbox WHERE status='PENDING' AND priority='LOW' ORDER BY id ASC LIMIT 50
                    )
                    """
                )
            )

    def drain_batch(self, sync_fn: Any, limit: int = 10) -> int:
        """
        Drains up to `limit` pending items.
        sync_fn: Callable[[target, payload_type, payload_dict], bool]
        """
        now = utc_now()
        rows = self.repository._read(
            "SELECT * FROM sync_outbox WHERE status='PENDING' AND next_attempt_at <= ? ORDER BY id ASC LIMIT ?",
            (now, limit)
        )
        processed = 0
        for r in rows:
            row_id = r["id"]
            attempts = r["attempts"] + 1
            payload = json.loads(r["payload_json"])

            success = False
            last_err = None
            try:
                success = sync_fn(r["target"], r["payload_type"], payload)
            except Exception as e:
                last_err = str(e)

            if success:
                self.repository.writer.submit(
                    lambda db, rid=row_id, ts=utc_now(): db.execute(
                        "UPDATE sync_outbox SET status='SYNCED', updated_at=? WHERE id=?",
                        (ts, rid)
                    )
                )
                processed += 1
            else:
                if attempts >= self.max_attempts:
                    new_status = "DEAD_LETTER"
                    next_attempt = now
                else:
                    new_status = "PENDING"
                    # Exponential backoff with jitter
                    backoff = min(self.backoff_max, self.backoff_base * (2 ** (attempts - 1)))
                    jitter = backoff * random.uniform(-self.jitter_factor, self.jitter_factor)
                    wait_sec = max(0.5, backoff + jitter)
                    next_attempt = datetime.fromtimestamp(
                        datetime.now(timezone.utc).timestamp() + wait_sec, tz=timezone.utc
                    ).isoformat()

                self.repository.writer.submit(
                    lambda db, rid=row_id, st=new_status, att=attempts, na=next_attempt, err=last_err, ts=utc_now(): db.execute(
                        "UPDATE sync_outbox SET status=?, attempts=?, next_attempt_at=?, last_error=?, updated_at=? WHERE id=?",
                        (st, att, na, err, ts, rid)
                    )
                )

        return processed

    def status_summary(self) -> Dict[str, int]:
        rows = self.repository._read("SELECT status, count(*) as count FROM sync_outbox GROUP BY status")
        counts = {"PENDING": 0, "SYNCED": 0, "DEAD_LETTER": 0}
        for r in rows:
            counts[r["status"]] = r["count"]
        return counts

    def catch_up(self, sync_fn: Any, batch_size: int = 50, max_batches: int = 20) -> int:
        """
        Drains multiple batches in succession after network outage recovery.
        Returns total successfully processed items.
        """
        total = 0
        for _ in range(max_batches):
            processed = self.drain_batch(sync_fn, limit=batch_size)
            total += processed
            if processed < batch_size:
                break
        return total

    def reset_backoff_for_catchup(self) -> None:
        """
        Resets next_attempt_at to current timestamp for all PENDING items
        so that network reconnection immediately processes accumulated backlog.
        """
        now = utc_now()
        self.repository.writer.submit(
            lambda db: db.execute(
                "UPDATE sync_outbox SET next_attempt_at=? WHERE status='PENDING'",
                (now,)
            )
        )

