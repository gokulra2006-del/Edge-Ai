"""User credentials management with secure hashing (bcrypt/pbkdf2) and automatic migration."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Tuple

from src.modules.logging.logger import LOGGER

try:
    import bcrypt  # type: ignore
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False

ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_USERS_PATH = ROOT_DIR / "src" / "config" / "dashboard_users.local.json"
ALLOWED_ROLES = {"COMMANDER", "OPERATOR", "ENGINEER", "VIEWER"}


def hash_password(plain_password: str) -> str:
    """Hashes a password using bcrypt if installed, otherwise pbkdf2_hmac_sha256."""
    if HAS_BCRYPT:
        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
        return hashed.decode("utf-8")
    else:
        # Fallback to PBKDF2-HMAC-SHA256
        salt = os.urandom(16)
        key = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, 100000)
        salt_b64 = base64.b64encode(salt).decode("ascii")
        key_b64 = base64.b64encode(key).decode("ascii")
        return f"$pbkdf2$sha256$100000${salt_b64}${key_b64}"


def is_hash(value: str) -> bool:
    """Detects whether a stored password string is a secure hash."""
    if not value or not isinstance(value, str):
        return False
    if value.startswith(("$2a$", "$2b$", "$2y$", "$pbkdf2$", "$argon2")):
        return True
    return False


def verify_password(plain_password: str, stored_value: str) -> Tuple[bool, bool]:
    """
    Verifies a plain password against stored value.
    Returns: (is_valid, needs_rehash).
    If stored_value is plain text and matches, returns (True, True) to trigger auto-upgrade.
    """
    if not stored_value or not plain_password:
        return False, False

    # 1. Bcrypt hash
    if stored_value.startswith(("$2a$", "$2b$", "$2y$")):
        if HAS_BCRYPT:
            try:
                valid = bcrypt.checkpw(plain_password.encode("utf-8"), stored_value.encode("utf-8"))
                return valid, False
            except Exception:
                return False, False
        else:
            LOGGER.error("Stored password is bcrypt but bcrypt module is unavailable.")
            return False, False

    # 2. PBKDF2 hash
    if stored_value.startswith("$pbkdf2$"):
        try:
            parts = stored_value.split("$")
            # Format: ['', 'pbkdf2', 'sha256', '100000', salt_b64, key_b64]
            algo = parts[2]
            rounds = int(parts[3])
            salt = base64.b64decode(parts[4])
            expected_key = base64.b64decode(parts[5])
            computed = hashlib.pbkdf2_hmac(algo, plain_password.encode("utf-8"), salt, rounds)
            valid = hmac.compare_digest(computed, expected_key)
            # If bcrypt is available now, rehash to bcrypt
            needs_rehash = HAS_BCRYPT
            return valid, needs_rehash
        except Exception:
            return False, False

    # 3. Plain-text legacy password migration path
    matches_plain = hmac.compare_digest(stored_value, plain_password)
    if matches_plain:
        return True, True  # Valid, but MUST BE REHASHED immediately

    return False, False


class UserManager:
    """Manages dashboard user accounts with secure hashing and role validation."""

    def __init__(self, users_file: Optional[Path] = None):
        self.users_file = users_file or DEFAULT_USERS_PATH
        self._lock = threading.Lock()
        self._ensure_file()

    def _ensure_file(self) -> None:
        if not self.users_file.exists():
            self.users_file.parent.mkdir(parents=True, exist_ok=True)
            self.users_file.write_text("{}", encoding="utf-8")

    def _load_users(self) -> Dict[str, Dict[str, str]]:
        try:
            if not self.users_file.exists():
                return {}
            data = json.loads(self.users_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            return {}
        except Exception as e:
            LOGGER.error(f"Error loading user store: {e}")
            return {}

    def _save_users(self, users: Dict[str, Dict[str, str]]) -> None:
        self.users_file.parent.mkdir(parents=True, exist_ok=True)
        self.users_file.write_text(json.dumps(users, indent=2), encoding="utf-8")

    def is_first_run(self) -> bool:
        """Returns True if no users exist in the user store."""
        users = self._load_users()
        return len(users) == 0

    def get_user(self, username: str) -> Optional[Dict[str, str]]:
        users = self._load_users()
        u = users.get(username.lower().strip())
        if u:
            return {"username": username.lower().strip(), "role": u.get("role", "VIEWER")}
        return None

    def list_users(self) -> List[Dict[str, str]]:
        users = self._load_users()
        return [{"username": k, "role": v.get("role", "VIEWER")} for k, v in users.items()]

    def authenticate(self, username: str, password: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Authenticates a user.
        Returns: (success, role_or_none, error_reason_or_none).
        Automatically upgrades plain-text passwords to secure hashes upon login.
        """
        username_clean = username.lower().strip()
        users = self._load_users()
        user_record = users.get(username_clean)
        if not user_record:
            return False, None, "UNKNOWN_USER"

        stored_pw = user_record.get("password", "")
        role = user_record.get("role", "VIEWER")

        valid, needs_rehash = verify_password(password, stored_pw)
        if not valid:
            return False, None, "INVALID_CREDENTIALS"

        # Migrate password to secure hash if plain text was used
        if needs_rehash:
            with self._lock:
                new_hash = hash_password(password)
                current_users = self._load_users()
                if username_clean in current_users:
                    current_users[username_clean]["password"] = new_hash
                    self._save_users(current_users)
                    LOGGER.info(f"User {username_clean} password automatically upgraded to secure hash.")

        return True, role, None

    def create_user(self, username: str, password: str, role: str) -> Dict[str, Any]:
        """Creates or updates a user with a hashed password."""
        username_clean = username.lower().strip()
        if not username_clean or len(username_clean) < 3:
            raise ValueError("Username must be at least 3 characters long")
        if not password or len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")
        role_upper = role.upper().strip()
        if role_upper not in ALLOWED_ROLES:
            raise ValueError(f"Invalid role: {role}. Allowed roles: {', '.join(sorted(ALLOWED_ROLES))}")

        with self._lock:
            users = self._load_users()
            users[username_clean] = {
                "password": hash_password(password),
                "role": role_upper,
            }
            self._save_users(users)

        LOGGER.info(f"User {username_clean} created with role {role_upper}.")
        return {"username": username_clean, "role": role_upper}

    def delete_user(self, username: str) -> bool:
        username_clean = username.lower().strip()
        with self._lock:
            users = self._load_users()
            if username_clean in users:
                del users[username_clean]
                self._save_users(users)
                LOGGER.info(f"User {username_clean} deleted.")
                return True
        return False

    def migrate_all_passwords(self) -> int:
        """Scans user store and hashes any remaining plain-text passwords."""
        migrated = 0
        with self._lock:
            users = self._load_users()
            for u, data in users.items():
                pw = data.get("password", "")
                if not is_hash(pw):
                    data["password"] = hash_password(pw)
                    migrated += 1
            if migrated > 0:
                self._save_users(users)
        return migrated
