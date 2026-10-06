"""Session management with idle/absolute timeouts, CSRF tokens, and logout invalidation."""
from __future__ import annotations

import hmac
import os
import secrets
import threading
import time
from typing import Any, Dict, Optional, Tuple


class SessionManager:
    """Thread-safe session state store enforcing timeouts and CSRF validation."""

    def __init__(
        self,
        idle_timeout_seconds: Optional[int] = None,
        absolute_timeout_seconds: Optional[int] = None,
    ):
        self.idle_timeout = idle_timeout_seconds or int(os.environ.get("SENTINEL_SESSION_IDLE_TIMEOUT", 1800))
        self.absolute_timeout = absolute_timeout_seconds or int(os.environ.get("SENTINEL_SESSION_ABSOLUTE_TIMEOUT", 28800))
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_session(self, operator_id: str, role: str) -> Dict[str, Any]:
        """Creates a new session with cryptographically secure token and CSRF token."""
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        now = time.time()

        session_data = {
            "token": token,
            "operator_id": operator_id,
            "role": role,
            "created_at": now,
            "last_active_at": now,
            "csrf_token": csrf_token,
        }

        with self._lock:
            self._sessions[token] = session_data

        return session_data

    def get_session(self, token: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Retrieves active session if valid.
        Returns: (session_or_none, expiration_reason_or_none).
        Enforces idle timeout and absolute session timeout.
        """
        if not token:
            return None, "NO_TOKEN"

        now = time.time()
        with self._lock:
            session = self._sessions.get(token)
            if not session:
                return None, "SESSION_NOT_FOUND"

            # Check absolute timeout
            if now - session["created_at"] > self.absolute_timeout:
                del self._sessions[token]
                return None, "ABSOLUTE_TIMEOUT"

            # Check idle timeout
            if now - session["last_active_at"] > self.idle_timeout:
                del self._sessions[token]
                return None, "IDLE_TIMEOUT"

            # Slide idle window
            session["last_active_at"] = now
            return dict(session), None

    def invalidate_session(self, token: str) -> bool:
        """Invalidates a session upon logout."""
        with self._lock:
            if token in self._sessions:
                del self._sessions[token]
                return True
        return False

    def validate_csrf(self, token: str, csrf_token_header: Optional[str]) -> bool:
        """Validates that the CSRF token in the request matches the session CSRF token."""
        if not csrf_token_header or not token:
            return False

        with self._lock:
            session = self._sessions.get(token)
            if not session:
                return False
            expected = session.get("csrf_token", "")
            return hmac.compare_digest(expected, csrf_token_header)

    def prune_expired(self) -> int:
        """Removes expired sessions from memory."""
        now = time.time()
        pruned = 0
        with self._lock:
            expired_keys = []
            for t, s in self._sessions.items():
                if (now - s["created_at"] > self.absolute_timeout) or (now - s["last_active_at"] > self.idle_timeout):
                    expired_keys.append(t)
            for k in expired_keys:
                del self._sessions[k]
                pruned += 1
        return pruned

    def active_session_count(self) -> int:
        with self._lock:
            return len(self._sessions)


SESSION_MANAGER = SessionManager()
