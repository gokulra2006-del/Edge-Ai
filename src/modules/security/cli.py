"""CLI for operator account management, first-run setup, and password migration."""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from src.modules.security.user_store import UserManager, ALLOWED_ROLES


def main() -> None:
    parser = argparse.ArgumentParser(description="Sentinel-AI Security & User Account Manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Setup Admin
    setup_p = subparsers.add_parser("setup-admin", help="First-run initial administrator creation")
    setup_p.add_argument("--username", default="commander", help="Admin username (default: commander)")
    setup_p.add_argument("--password", help="Admin password (prompts securely if omitted)")

    # 2. Add User
    add_p = subparsers.add_parser("add-user", help="Create or update an operator account")
    add_p.add_argument("username", help="Username")
    add_p.add_argument("--role", required=True, choices=list(sorted(ALLOWED_ROLES)), help="Operator role")
    add_p.add_argument("--password", help="Password (prompts securely if omitted)")

    # 3. List Users
    subparsers.add_parser("list-users", help="List all registered operator accounts")

    # 4. Delete User
    del_p = subparsers.add_parser("delete-user", help="Delete an operator account")
    del_p.add_argument("username", help="Username to delete")

    # 5. Migrate Passwords
    subparsers.add_parser("migrate-passwords", help="Hash any remaining plain-text passwords")

    args = parser.parse_args()
    user_mgr = UserManager()

    if args.command == "setup-admin":
        if not user_mgr.is_first_run():
            print("Notice: User accounts already exist. Use 'add-user' to manage accounts.")
        pw = args.password
        if not pw:
            pw = getpass.getpass(f"Enter password for admin '{args.username}': ")
            pw_conf = getpass.getpass("Confirm password: ")
            if pw != pw_conf:
                print("Error: Passwords do not match.", file=sys.stderr)
                sys.exit(1)
        res = user_mgr.create_user(args.username, pw, "COMMANDER")
        print(f"Initial administrator '{res['username']}' created successfully with role COMMANDER.")
        sys.exit(0)

    elif args.command == "add-user":
        pw = args.password
        if not pw:
            pw = getpass.getpass(f"Enter password for '{args.username}': ")
            pw_conf = getpass.getpass("Confirm password: ")
            if pw != pw_conf:
                print("Error: Passwords do not match.", file=sys.stderr)
                sys.exit(1)
        res = user_mgr.create_user(args.username, pw, args.role)
        print(f"User '{res['username']}' created/updated successfully with role {res['role']}.")
        sys.exit(0)

    elif args.command == "list-users":
        users = user_mgr.list_users()
        print(json.dumps(users, indent=2))
        sys.exit(0)

    elif args.command == "delete-user":
        ok = user_mgr.delete_user(args.username)
        if ok:
            print(f"User '{args.username}' deleted successfully.")
            sys.exit(0)
        else:
            print(f"Error: User '{args.username}' not found.", file=sys.stderr)
            sys.exit(1)

    elif args.command == "migrate-passwords":
        count = user_mgr.migrate_all_passwords()
        print(f"Migrated and hashed {count} plain-text password(s).")
        sys.exit(0)


if __name__ == "__main__":
    main()
