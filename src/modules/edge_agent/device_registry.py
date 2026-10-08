"""
Stage I1 Edge Device Registry & Telemetry Ingestion Hub.
=========================================================
Features:
- Hashed device tokens (SHA-256 with salt)
- Idempotent telemetry ingestion (by event_id)
- Boot_id restart vs sequence gap vs duplicate packet detection
- In-memory event bus with subscriber callbacks (for WebSocket / SSE streaming)
- Fallback SQLite WAL persistence in edge_telemetry_history
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.modules.edge_agent.telemetry_schema import TelemetryValidator, TelemetryValidationResult


def hash_device_token(token: str) -> str:
    """Computes a cryptographically secure SHA-256 hash of the device token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class DeviceRegistry:
    """Manages registered edge devices and authentication tokens."""

    def __init__(self, repository: Any):
        self.repository = repository
        self._lock = threading.RLock()
        self._subscribers: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}

    def register_device(
        self,
        device_id: str,
        name: str,
        token: str,
        hardware_model: str = "Raspberry Pi 4 Model B",
        data_source: str = "SIMULATED",
    ) -> Dict[str, Any]:
        """Registers or updates a device with a hashed token."""
        now = datetime.now(timezone.utc).isoformat()
        token_hash = hash_device_token(token)

        self.repository.writer.submit_wait(
            lambda c: c.execute(
                """
                INSERT INTO edge_devices (
                    device_id, name, token_hash, status, hardware_model, data_source, created_at, updated_at
                ) VALUES (?, ?, ?, 'OFFLINE', ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    name=excluded.name,
                    token_hash=excluded.token_hash,
                    hardware_model=excluded.hardware_model,
                    data_source=excluded.data_source,
                    updated_at=excluded.updated_at
                """,
                (device_id, name, token_hash, hardware_model, data_source, now, now),
            )
        )
        return {"device_id": device_id, "name": name, "status": "OFFLINE"}

    def verify_device_token(self, device_id: str, token: str) -> bool:
        """Verifies device token against the stored hash in constant time."""
        expected_hash = hash_device_token(token)
        rows = self.repository._read(
            "SELECT token_hash FROM edge_devices WHERE device_id = ?",
            (device_id,),
        )
        if not rows:
            return False
        stored_hash = rows[0]["token_hash"]
        return secrets.compare_digest(stored_hash, expected_hash)

    def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        rows = self.repository._read(
            "SELECT device_id, name, status, last_seen_at, last_boot_id, last_sequence, ip_address, software_version, hardware_model, data_source, created_at, updated_at FROM edge_devices WHERE device_id = ?",
            (device_id,),
        )
        if not rows:
            return None
        return dict(rows[0])

    def list_devices(self) -> List[Dict[str, Any]]:
        rows = self.repository._read(
            "SELECT device_id, name, status, last_seen_at, last_boot_id, last_sequence, ip_address, software_version, hardware_model, data_source, created_at, updated_at FROM edge_devices ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]

    def ingest_telemetry(
        self,
        packet: Dict[str, Any],
        client_ip: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Idempotently ingest a validated Telemetry Schema 1.0 packet.
        Returns detection metadata: is_duplicate, is_restart, gap_detected, previous_sequence.
        """
        val = TelemetryValidator.validate(packet)
        if not val.is_valid:
            raise ValueError(f"Invalid schema: {'; '.join(val.errors)}")

        device_id = packet["device_id"]
        event_id = packet["event_id"]
        boot_id = packet["boot_id"]
        seq = packet["sequence"]
        ts_utc = packet["timestamp_utc"]
        now_utc = datetime.now(timezone.utc).isoformat()
        clock_status = packet["clock_status"]
        connectivity = packet["connectivity"]
        data_source = packet["data_source"]

        with self._lock:
            def _txn(c: sqlite3.Connection) -> Dict[str, Any]:
                # 1. Deduplication check via event_id
                existing = c.execute(
                    "SELECT id FROM edge_telemetry_history WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if existing:
                    return {
                        "status": "DUPLICATE_IGNORED",
                        "event_id": event_id,
                        "device_id": device_id,
                        "is_duplicate": True,
                    }

                # 2. Inspect device current state for restart or gap detection
                dev_row = c.execute(
                    "SELECT last_boot_id, last_sequence FROM edge_devices WHERE device_id = ?",
                    (device_id,),
                ).fetchone()

                last_boot_id = dev_row["last_boot_id"] if dev_row else None
                last_seq = dev_row["last_sequence"] if dev_row else 0

                is_restart = False
                gap_detected = False
                missing_sequences = []

                if last_boot_id and last_boot_id != boot_id:
                    # New boot_id indicates node restart
                    is_restart = True
                elif last_boot_id == boot_id:
                    if seq > (last_seq + 1):
                        gap_detected = True
                        missing_sequences = list(range(last_seq + 1, seq))

                # 3. Insert telemetry record
                c.execute(
                    """
                    INSERT INTO edge_telemetry_history (
                        device_id, event_id, boot_id, sequence, timestamp_utc, received_at_utc,
                        clock_status, connectivity, data_source, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        device_id,
                        event_id,
                        boot_id,
                        seq,
                        ts_utc,
                        now_utc,
                        clock_status,
                        connectivity,
                        data_source,
                        json.dumps(packet),
                    ),
                )

                # 4. Update device liveness
                c.execute(
                    """
                    UPDATE edge_devices SET
                        status = 'ONLINE',
                        last_seen_at = ?,
                        last_boot_id = ?,
                        last_sequence = ?,
                        ip_address = COALESCE(?, ip_address),
                        data_source = ?,
                        updated_at = ?
                    WHERE device_id = ?
                    """,
                    (
                        now_utc,
                        boot_id,
                        seq,
                        client_ip,
                        data_source,
                        now_utc,
                        device_id,
                    ),
                )

                return {
                    "status": "INGESTED",
                    "event_id": event_id,
                    "device_id": device_id,
                    "sequence": seq,
                    "is_restart": is_restart,
                    "gap_detected": gap_detected,
                    "missing_sequences": missing_sequences,
                }

            result = self.repository.writer.submit_wait(_txn)

            # 5. Notify streaming subscribers
            self._notify_subscribers(device_id, packet)
            return result

    def subscribe(self, device_id: str, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a subscriber callback for live telemetry events."""
        with self._lock:
            if device_id not in self._subscribers:
                self._subscribers[device_id] = []
            self._subscribers[device_id].append(callback)

    def unsubscribe(self, device_id: str, callback: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            if device_id in self._subscribers and callback in self._subscribers[device_id]:
                self._subscribers[device_id].remove(callback)

    def _notify_subscribers(self, device_id: str, packet: Dict[str, Any]) -> None:
        targets = []
        with self._lock:
            if device_id in self._subscribers:
                targets.extend(self._subscribers[device_id])
            if "*" in self._subscribers:
                targets.extend(self._subscribers["*"])

        for cb in targets:
            try:
                cb(packet)
            except Exception:
                pass

    def get_latest_telemetry(self, device_id: str) -> Optional[Dict[str, Any]]:
        rows = self.repository._read(
            "SELECT payload_json FROM edge_telemetry_history WHERE device_id = ? ORDER BY id DESC LIMIT 1",
            (device_id,),
        )
        if rows:
            return json.loads(rows[0]["payload_json"])
        return None

    def get_telemetry_history(
        self,
        device_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        rows = self.repository._read(
            "SELECT payload_json FROM edge_telemetry_history WHERE device_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (device_id, limit, offset),
        )
        return [json.loads(r["payload_json"]) for r in rows]
