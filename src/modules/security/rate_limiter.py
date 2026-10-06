"""Login rate limiting, lockout enforcement, and audit ledger logging."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from src.modules.database.governed_store import IncidentRepository, utc_now
from src.modules.logging.logger import LOGGER


class LoginRateLimiter:
    """Tracks failed login attempts and enforces temporary lockouts with audit logging."""

    def __init__(
        self,
        repository: Optional[IncidentRepository] = None,
        max_attempts: Optional[int] = None,
        lockout_seconds: Optional[int] = None,
        window_seconds: int = 300,
    ):
        self.repository = repository
        self.max_attempts = max_attempts or int(os.environ.get("SENTINEL_LOGIN_MAX_ATTEMPTS", 5))
        self.lockout_seconds = lockout_seconds or int(os.environ.get("SENTINEL_LOGIN_LOCKOUT_SECONDS", 900))
        self.window_seconds = window_seconds

        # Key: client identifier (IP or username) -> list of failure timestamps
        self._failures: Dict[str, List[float]] = {}
        # Key: client identifier -> lockout expiration timestamp
        self._lockouts: Dict[str, float] = {}
        self._lock = threading.Lock()

    def is_locked_out(self, client_key: str) -> Tuple[bool, int]:
        """
        Checks if a client identifier is currently locked out.
        Returns: (is_locked, remaining_seconds).
        """
        now = time.time()
        with self._lock:
            lockout_expiry = self._lockouts.get(client_key)
            if lockout_expiry and lockout_expiry > now:
                remaining = int(lockout_expiry - now)
                return True, remaining
            elif lockout_expiry and lockout_expiry <= now:
                del self._lockouts[client_key]
                self._failures.pop(client_key, None)

        return False, 0

    def record_failure(self, client_key: str, username: str, reason: str, ip: str = "127.0.0.1") -> Tuple[bool, int]:
        """
        Records a failed login attempt.
        Returns: (is_now_locked_out, remaining_lockout_seconds).
        """
        now = time.time()
        locked = False
        remaining = 0

        with self._lock:
            timestamps = self._failures.setdefault(client_key, [])
            # Prune attempts outside window
            timestamps = [t for t in timestamps if now - t <= self.window_seconds]
            timestamps.append(now)
            self._failures[client_key] = timestamps

            if len(timestamps) >= self.max_attempts:
                self._lockouts[client_key] = now + self.lockout_seconds
                locked = True
                remaining = self.lockout_seconds
                LOGGER.warning(f"Login lockout triggered for '{client_key}' ({self.lockout_seconds}s).")

        # Audit log into SQLite
        self._audit_log(
            operator_id=username or "UNKNOWN",
            action="login_failure",
            approved=0,
            payload={
                "client_key": client_key,
                "reason": reason,
                "ip": ip,
                "locked_out": locked,
                "remaining_lockout_seconds": remaining,
            },
        )

        return locked, remaining

    def record_success(self, client_key: str, username: str, ip: str = "127.0.0.1") -> None:
        """Clears failure history for the client upon successful authentication and audit logs."""
        with self._lock:
            self._failures.pop(client_key, None)
            self._lockouts.pop(client_key, None)

        self._audit_log(
            operator_id=username,
            action="login_success",
            approved=1,
            payload={"client_key": client_key, "ip": ip},
        )

    def _audit_log(self, operator_id: str, action: str, approved: int, payload: Dict[str, Any]) -> None:
        if not self.repository:
            return
        payload_str = json.dumps(payload, sort_keys=True)
        ts = utc_now()
        def _write(db):
            db.execute(
                """
                INSERT OR IGNORE INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at)
                VALUES('SYSTEM', 'sys-audit-anchor', 'SYSTEM', 'SYSTEM', 'CLOSED', ?, ?)
                """,
                (ts, ts),
            )
            db.execute(
                """
                INSERT INTO operator_actions (incident_id, timestamp, operator_id, action, approved, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("SYSTEM", ts, operator_id, action, approved, payload_str),
            )
        try:
            self.repository.writer.submit(_write)
        except Exception as e:
            LOGGER.error(f"Audit log writing failed: {e}")

    def reset(self) -> None:
        """Resets all rate limiting state (useful for tests)."""
        with self._lock:
            self._failures.clear()
            self._lockouts.clear()


RATE_LIMITER = LoginRateLimiter()
