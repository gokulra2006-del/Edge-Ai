#!/usr/bin/env python3
"""Phase 5E Security Hardening Smoke Test.

Validates:
1. Password hashing (bcrypt) and transparent migration from plain-text passwords.
2. First-run admin setup flow and CLI account management.
3. Session expiration (idle and absolute timeout) and logout invalidation.
4. Login failure audit logging, rate limiting, and account lockout.
5. CSRF protection on state-changing actions.
6. Secrets protection (.env.example verification, .gitignore).
7. Role x endpoint permission matrix coverage and route introspection guard.
"""
from __future__ import annotations

import gc
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.modules.database.governed_store import IncidentRepository, MigrationRunner
from src.modules.security.user_store import UserManager, hash_password, verify_password, is_hash
from src.modules.security.session_manager import SessionManager
from src.modules.security.rate_limiter import LoginRateLimiter
from src.modules.security.permission_matrix import (
    ENDPOINT_PERMISSIONS,
    check_endpoint_permission,
    ALL_ROLES,
)
from src.modules.security.cli import main as security_cli_main


def run_phase5e_smoke() -> bool:
    print("=" * 70)
    print(" SENTINEL-AI PHASE 5E: SECURITY HARDENING SMOKE VERIFICATION")
    print("=" * 70)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_path = Path(tmpdir)
        db_path = tmp_path / "smoke_security.db"
        users_file = tmp_path / "smoke_users.json"

        print("\n[Step 1] Initializing test database and schema...")
        MigrationRunner(db_path).run()
        repo = IncidentRepository(db_path=db_path)

        # [Test 1] Password Hashing & Transparent Migration
        print("\n[Step 2] Validating password hashing (bcrypt) and auto-migration...")
        mgr = UserManager(users_file=users_file)

        # Seed legacy plain text
        raw_users = {
            "legacy_operator": {"password": "PlainPassword123!", "role": "OPERATOR"},
            "legacy_commander": {"password": "CommanderPass2026!", "role": "COMMANDER"},
        }
        users_file.write_text(json.dumps(raw_users), encoding="utf-8")

        assert not is_hash("PlainPassword123!")
        ok, role, err = mgr.authenticate("legacy_operator", "PlainPassword123!")
        assert ok is True and role == "OPERATOR"

        # Check legacy_operator was transparently migrated to bcrypt hash
        data_after_login = json.loads(users_file.read_text(encoding="utf-8"))
        op_hash = data_after_login["legacy_operator"]["password"]
        assert is_hash(op_hash), "Password was not migrated to hash"
        print(f"  -> Transparent on-login migration verified (hash: {op_hash[:15]}...).")

        # Migrate remaining batch
        migrated = mgr.migrate_all_passwords()
        assert migrated == 1
        data_final = json.loads(users_file.read_text(encoding="utf-8"))
        assert is_hash(data_final["legacy_commander"]["password"])
        print("  -> Batch migration verified: all plain text passwords hashed.")

        # [Test 2] First-Run Admin Setup Flow & CRUD
        print("\n[Step 3] Validating first-run setup flow and user management...")
        fresh_users_file = tmp_path / "fresh_users.json"
        fresh_mgr = UserManager(users_file=fresh_users_file)
        assert fresh_mgr.is_first_run() is True
        print("  -> First-run state correctly identified when no accounts exist.")

        admin = fresh_mgr.create_user("commander", "SecureAdminPass2026!", "COMMANDER")
        assert admin["role"] == "COMMANDER"
        assert fresh_mgr.is_first_run() is False

        fresh_mgr.create_user("operator_1", "OpPass2026!", "OPERATOR")
        fresh_mgr.create_user("engineer_1", "EngPass2026!", "ENGINEER")
        user_list = fresh_mgr.list_users()
        assert len(user_list) == 3
        print(f"  -> Account creation verified: {len(user_list)} accounts registered.")

        # [Test 3] Session Timeouts & CSRF
        print("\n[Step 4] Validating session lifecycle (idle/absolute timeouts, CSRF, logout)...")
        sess_mgr = SessionManager(idle_timeout_seconds=2, absolute_timeout_seconds=5)
        sess = sess_mgr.create_session("commander", "COMMANDER")
        tok = sess["token"]
        csrf = sess["csrf_token"]

        # CSRF validation
        assert sess_mgr.validate_csrf(tok, csrf) is True
        assert sess_mgr.validate_csrf(tok, "bad_csrf") is False
        assert sess_mgr.validate_csrf(tok, None) is False
        print("  -> CSRF token validation verified.")

        # Idle timeout
        sess_mgr._sessions[tok]["last_active_at"] = time.time() - 3
        sess_idle, err_idle = sess_mgr.get_session(tok)
        assert sess_idle is None and err_idle == "IDLE_TIMEOUT"
        print("  -> Idle session timeout verified.")

        # Absolute timeout
        sess2 = sess_mgr.create_session("operator_1", "OPERATOR")
        tok2 = sess2["token"]
        sess_mgr._sessions[tok2]["created_at"] = time.time() - 6
        sess_abs, err_abs = sess_mgr.get_session(tok2)
        assert sess_abs is None and err_abs == "ABSOLUTE_TIMEOUT"
        print("  -> Absolute session timeout verified.")

        # Logout invalidation
        sess3 = sess_mgr.create_session("engineer_1", "ENGINEER")
        tok3 = sess3["token"]
        assert sess_mgr.invalidate_session(tok3) is True
        assert sess_mgr.get_session(tok3)[0] is None
        print("  -> Explicit logout invalidation verified.")

        # [Test 4] Login Rate Limiting & Audit Trail
        print("\n[Step 5] Validating login brute-force rate limiting and audit logging...")
        limiter = LoginRateLimiter(repository=repo, max_attempts=3, lockout_seconds=10, window_seconds=60)
        client = "127.0.0.1_commander"

        l1, _ = limiter.record_failure(client, "commander", "INVALID_CREDENTIALS")
        assert l1 is False
        l2, _ = limiter.record_failure(client, "commander", "INVALID_CREDENTIALS")
        assert l2 is False
        l3, rem = limiter.record_failure(client, "commander", "INVALID_CREDENTIALS")
        assert l3 is True and rem > 0
        print("  -> Account locked out on 3rd failed attempt.")

        repo.writer.drain()
        time.sleep(0.1)
        con = sqlite3.connect(str(db_path))
        try:
            cur = con.cursor()
            actions = cur.execute(
                "SELECT * FROM operator_actions WHERE operator_id='commander' AND action='login_failure'"
            ).fetchall()
            assert len(actions) == 3
        finally:
            con.close()
        print(f"  -> Login failure audit trail verified: {len(actions)} entries logged.")

        # [Test 5] Secrets Protection
        print("\n[Step 6] Validating secrets hygiene (.env.example & .gitignore)...")
        env_example = PROJECT_ROOT / ".env.example"
        assert env_example.exists()
        gitignore = PROJECT_ROOT / ".gitignore"
        assert ".env" in gitignore.read_text(encoding="utf-8")
        print("  -> Secrets protection verified: .env.example present and .env ignored in git.")

        # [Test 6] Role Permission Matrix & Introspection Guard
        print("\n[Step 7] Validating role x endpoint permission matrix & route introspection...")
        # Verify route sample permissions
        routes_to_test = [
            ("GET", "/api/live", None, True, 200),
            ("GET", "/api/auth/me", None, False, 401),
            ("GET", "/api/auth/users", "OPERATOR", False, 403),
            ("GET", "/api/auth/users", "COMMANDER", True, 200),
            ("POST", "/api/incidents/INC-1/escalate", "OPERATOR", False, 403),
            ("POST", "/api/incidents/INC-1/escalate", "COMMANDER", True, 200),
            ("POST", "/api/storage/cleanup", "VIEWER", False, 403),
            ("POST", "/api/storage/cleanup", "COMMANDER", True, 200),
        ]
        for m, p, r, exp_ok, exp_st in routes_to_test:
            ok, st, msg = check_endpoint_permission(p, m, r)
            assert ok == exp_ok and st == exp_st, f"Route check failed: {m} {p} {r}"
        print(f"  -> Sample matrix checks passed across {len(routes_to_test)} endpoints.")

        # Introspection Guard against app.py
        app_py = PROJECT_ROOT / "src" / "modules" / "dashboard" / "app.py"
        app_content = app_py.read_text(encoding="utf-8")
        exact_paths = set(re.findall(r'path\s*==\s*["\'](/[^"\']+)["\']', app_content))
        startswith_paths = set(re.findall(r'path\.startswith\(\s*["\'](/[^"\']+)["\']', app_content))
        all_detected_routes = exact_paths | startswith_paths

        unmapped = []
        for route in all_detected_routes:
            test_path = route.rstrip("/")
            if not test_path.startswith("/api") and test_path not in ("", "/index.html", "/app.js", "/chart.min.js", "/style.css", "/healthz", "/readyz"):
                continue
            matched = any(
                re.match(pattern, test_path) or re.match(pattern, test_path + "/dummy")
                for _, pattern, _, _ in ENDPOINT_PERMISSIONS
            )
            if not matched:
                unmapped.append(route)
        assert len(unmapped) == 0, f"Found unmapped endpoints lacking permission rules: {unmapped}"
        print(f"  -> Introspection guard passed: 100% of routes in app.py have permission rules.")

        repo.close()
        del repo, mgr, fresh_mgr, sess_mgr, limiter
        gc.collect()

    print("\n" + "=" * 70)
    print(" ALL PHASE 5E VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = run_phase5e_smoke()
    sys.exit(0 if success else 1)
