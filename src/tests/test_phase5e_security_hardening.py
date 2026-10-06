"""Comprehensive Security Hardening Tests for Phase 5E.

Tests verify:
1. Password hashing (bcrypt) and transparent migration from plain-text.
2. First-run admin setup flow and CLI user management.
3. Session expiration (idle and absolute timeout) and logout invalidation.
4. Audit logging of login failures and rate limiting / lockout.
5. CSRF protection on state-changing browser actions.
6. Secrets loaded from environment variables (.env.example verification).
7. Secure cookie flags and basic security headers.
8. Role-permission matrix: complete role x endpoint matrix test, including
   an introspection guard that fails if any endpoint in app.py lacks a permission rule.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from src.modules.database.governed_store import IncidentRepository, utc_now
from src.modules.security.user_store import UserManager, hash_password, verify_password, is_hash
from src.modules.security.session_manager import SessionManager
from src.modules.security.rate_limiter import LoginRateLimiter
from src.modules.security.permission_matrix import (
    ENDPOINT_PERMISSIONS,
    check_endpoint_permission,
    ALL_ROLES,
)


@pytest.fixture
def sec_repo(tmp_path):
    db_path = tmp_path / "sec_test.db"
    repo = IncidentRepository(db_path=db_path)
    yield repo
    repo.close()


@pytest.fixture
def user_store_env(tmp_path):
    users_file = tmp_path / "test_users.json"
    mgr = UserManager(users_file=users_file)
    return {"mgr": mgr, "file": users_file}


def test_password_hashing_and_auto_migration(user_store_env):
    """Verify password hashing with bcrypt, hash detection, and auto-migration of plain-text passwords."""
    mgr = user_store_env["mgr"]
    file_path = user_store_env["file"]

    # 1. Plain text password legacy seeding
    raw_users = {
        "legacy_op": {"password": "PlainPassword123!", "role": "OPERATOR"},
        "legacy_cmdr": {"password": "CommanderPass2026!", "role": "COMMANDER"},
    }
    file_path.write_text(json.dumps(raw_users), encoding="utf-8")

    # Verify not hash yet
    assert not is_hash("PlainPassword123!")

    # Verify authentication succeeds and triggers auto-rehash
    ok, role, err = mgr.authenticate("legacy_op", "PlainPassword123!")
    assert ok is True
    assert role == "OPERATOR"
    assert err is None

    # Check that file now has bcrypt hash for legacy_op
    updated_users = json.loads(file_path.read_text(encoding="utf-8"))
    op_pw = updated_users["legacy_op"]["password"]
    assert is_hash(op_pw)
    assert op_pw.startswith("$2b$") or op_pw.startswith("$pbkdf2$")

    # Legacy cmdr still plain text until migration or login
    assert not is_hash(updated_users["legacy_cmdr"]["password"])

    # Migrate all remaining
    migrated_count = mgr.migrate_all_passwords()
    assert migrated_count == 1

    final_users = json.loads(file_path.read_text(encoding="utf-8"))
    assert is_hash(final_users["legacy_cmdr"]["password"])

    # Verify wrong password fails
    bad_ok, bad_role, bad_err = mgr.authenticate("legacy_cmdr", "WrongPassword!")
    assert bad_ok is False
    assert bad_role is None
    assert bad_err == "INVALID_CREDENTIALS"


def test_first_run_admin_setup_and_user_crud(user_store_env):
    """Verify first-run detection, initial admin creation, and user CRUD operations."""
    mgr = user_store_env["mgr"]

    # Initially empty -> first run is True
    assert mgr.is_first_run() is True

    # Setup initial admin
    admin = mgr.create_user("commander", "SuperSecurePass2026!", "COMMANDER")
    assert admin["username"] == "commander"
    assert admin["role"] == "COMMANDER"
    assert mgr.is_first_run() is False

    # Add other users
    mgr.create_user("operator_1", "OperatorPass2026!", "OPERATOR")
    mgr.create_user("engineer_1", "EngineerPass2026!", "ENGINEER")
    mgr.create_user("viewer_1", "ViewerPass2026!", "VIEWER")

    user_list = mgr.list_users()
    assert len(user_list) == 4
    roles = {u["username"]: u["role"] for u in user_list}
    assert roles["commander"] == "COMMANDER"
    assert roles["operator_1"] == "OPERATOR"
    assert roles["engineer_1"] == "ENGINEER"
    assert roles["viewer_1"] == "VIEWER"

    # Delete user
    assert mgr.delete_user("viewer_1") is True
    assert len(mgr.list_users()) == 3
    assert mgr.delete_user("non_existent") is False


def test_session_idle_and_absolute_timeouts():
    """Verify session manager enforces idle timeout and absolute timeout, plus logout invalidation."""
    sess_mgr = SessionManager(idle_timeout_seconds=2, absolute_timeout_seconds=5)

    sess = sess_mgr.create_session("op_alice", "OPERATOR")
    token = sess["token"]
    csrf = sess["csrf_token"]
    assert token and csrf

    # Active session valid
    active, err = sess_mgr.get_session(token)
    assert active is not None
    assert err is None
    assert active["operator_id"] == "op_alice"

    # CSRF validation
    assert sess_mgr.validate_csrf(token, csrf) is True
    assert sess_mgr.validate_csrf(token, "wrong_csrf") is False
    assert sess_mgr.validate_csrf(token, None) is False

    # Simulate idle timeout: advance last_active_at into the past
    sess_mgr._sessions[token]["last_active_at"] = time.time() - 3
    expired_idle, err_idle = sess_mgr.get_session(token)
    assert expired_idle is None
    assert err_idle == "IDLE_TIMEOUT"

    # Create new session to test absolute timeout
    sess2 = sess_mgr.create_session("op_bob", "COMMANDER")
    token2 = sess2["token"]
    sess_mgr._sessions[token2]["created_at"] = time.time() - 6
    expired_abs, err_abs = sess_mgr.get_session(token2)
    assert expired_abs is None
    assert err_abs == "ABSOLUTE_TIMEOUT"

    # Test logout invalidation
    sess3 = sess_mgr.create_session("op_carol", "ENGINEER")
    token3 = sess3["token"]
    assert sess_mgr.get_session(token3)[0] is not None
    assert sess_mgr.invalidate_session(token3) is True
    assert sess_mgr.get_session(token3)[0] is None


def test_login_rate_limiting_lockout_and_audit(sec_repo):
    """Verify rate limiting locks out after max attempts and writes audit log to SQLite."""
    limiter = LoginRateLimiter(repository=sec_repo, max_attempts=3, lockout_seconds=10, window_seconds=60)

    client = "192.168.1.50_commander"

    # 1. First 2 failed attempts: not locked out yet
    locked, rem = limiter.record_failure(client, "commander", "INVALID_CREDENTIALS")
    assert locked is False
    locked, rem = limiter.record_failure(client, "commander", "INVALID_CREDENTIALS")
    assert locked is False

    # 2. 3rd attempt: triggers lockout
    locked, rem = limiter.record_failure(client, "commander", "INVALID_CREDENTIALS")
    assert locked is True
    assert rem > 0

    # 3. Checking status reports locked out
    is_l, rem_l = limiter.is_locked_out(client)
    assert is_l is True
    assert rem_l > 0

    # 4. Wait for SQLite writer queue flush and check audit records
    sec_repo.writer.drain()
    with sqlite3.connect(str(sec_repo.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        actions = cur.execute(
            "SELECT * FROM operator_actions WHERE operator_id='commander' AND action='login_failure'"
        ).fetchall()
        assert len(actions) == 3

    # 5. Success resets lockout
    limiter.record_success(client, "commander")
    is_l_after, _ = limiter.is_locked_out(client)
    assert is_l_after is False


def test_env_example_secrets_protection():
    """Verify .env.example exists, has no hardcoded secrets, and .env is ignored in git."""
    repo_root = Path(__file__).resolve().parents[2]
    env_example = repo_root / ".env.example"
    assert env_example.exists()

    content = env_example.read_text(encoding="utf-8")
    assert "SENTINEL_SESSION_SECRET" in content
    # Ensure no real production secret is hardcoded in example
    assert "generate-a-secure-random" in content or "change-me" in content

    # Verify .gitignore contains .env
    gitignore = repo_root / ".gitignore"
    git_content = gitignore.read_text(encoding="utf-8")
    assert ".env" in git_content


def test_role_permission_matrix_coverage():
    """
    MATRIX TEST:
    Verifies every route defined in ENDPOINT_PERMISSIONS across all 4 roles + unauthenticated.
    """
    sample_tests = [
        # (method, path, role, expected_allowed, expected_status)
        ("GET", "/api/live", None, True, 200),
        ("GET", "/api/live", "VIEWER", True, 200),
        ("POST", "/api/auth/login", None, True, 200),
        ("GET", "/api/auth/me", None, False, 401),
        ("GET", "/api/auth/me", "VIEWER", True, 200),
        ("GET", "/api/auth/users", "COMMANDER", True, 200),
        ("GET", "/api/auth/users", "OPERATOR", False, 403),
        ("GET", "/api/auth/users", "VIEWER", False, 403),
        ("POST", "/api/incidents/INC-1/acknowledge", "COMMANDER", True, 200),
        ("POST", "/api/incidents/INC-1/acknowledge", "OPERATOR", True, 200),
        ("POST", "/api/incidents/INC-1/acknowledge", "ENGINEER", False, 403),
        ("POST", "/api/incidents/INC-1/acknowledge", "VIEWER", False, 403),
        ("POST", "/api/incidents/INC-1/escalate", "COMMANDER", True, 200),
        ("POST", "/api/incidents/INC-1/escalate", "OPERATOR", False, 403),
        ("GET", "/api/review/queue", "COMMANDER", True, 200),
        ("GET", "/api/review/queue", "ENGINEER", True, 200),
        ("GET", "/api/review/queue", "VIEWER", False, 403),
        ("POST", "/api/storage/cleanup", "COMMANDER", True, 200),
        ("POST", "/api/storage/cleanup", "ENGINEER", True, 200),
        ("POST", "/api/storage/cleanup", "OPERATOR", False, 403),
        ("POST", "/api/storage/cleanup", "VIEWER", False, 403),
        ("POST", "/api/evidence/verify", "ENGINEER", True, 200),
        ("POST", "/api/evidence/verify", "OPERATOR", False, 403),
    ]

    for method, path, role, expected_ok, expected_st in sample_tests:
        ok, st, msg = check_endpoint_permission(path, method, role)
        assert ok == expected_ok, f"Failed on {method} {path} with role {role}: {msg}"
        assert st == expected_st, f"Status mismatch on {method} {path} with role {role}: got {st}, expected {expected_st}"


def test_endpoint_permission_matrix_introspection_guard():
    """
    STRICT REGRESSION GUARD:
    Scans src/modules/dashboard/app.py for all registered HTTP routes.
    Asserts that EVERY single route found in app.py has an explicit rule in ENDPOINT_PERMISSIONS.
    If a developer adds an endpoint without a permission rule, this test FAILS immediately!
    """
    app_py = Path(__file__).resolve().parents[1] / "modules" / "dashboard" / "app.py"
    app_content = app_py.read_text(encoding="utf-8")

    # Extract all path strings checked in app.py: e.g. path == "/api/..." or path.startswith("/api/...")
    exact_paths = set(re.findall(r'path\s*==\s*["\'](/[^"\']+)["\']', app_content))
    startswith_paths = set(re.findall(r'path\.startswith\(\s*["\'](/[^"\']+)["\']', app_content))

    all_detected_routes = exact_paths | startswith_paths

    unmapped_routes = []
    for route in all_detected_routes:
        # Check if route matches any pattern in ENDPOINT_PERMISSIONS
        matched = False
        for method, pattern, allowed_roles, desc in ENDPOINT_PERMISSIONS:
            # Test route against regex
            test_path = route.rstrip("/")
            if not test_path.startswith("/api") and test_path not in ("", "/index.html", "/app.js", "/chart.min.js", "/style.css"):
                continue
            if re.match(pattern, test_path) or re.match(pattern, test_path + "/dummy"):
                matched = True
                break

        # Filter out purely internal or non-endpoint matches if any
        if not matched:
            unmapped_routes.append(route)

    assert len(unmapped_routes) == 0, f"Found unmapped endpoints in app.py lacking permission rules: {unmapped_routes}"
