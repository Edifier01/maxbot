"""Explicit, operator-authorized administrator password recovery command."""

from __future__ import annotations

import argparse
import getpass
import sys

from app import auth, auth_epoch, db_pg
from app.config import is_server_mode, require_database_url, require_jwt_secret


def _password_from_stdin() -> str:
    value = sys.stdin.readline()
    if value.endswith("\n"):
        value = value[:-1]
    if value.endswith("\r"):
        value = value[:-1]
    return value


def _read_password(*, stdin: bool) -> str:
    if stdin:
        password = _password_from_stdin()
        if not password:
            raise ValueError("empty password")
        return password
    first = getpass.getpass("New administrator password: ")
    second = getpass.getpass("Repeat administrator password: ")
    if first != second:
        raise ValueError("password confirmation does not match")
    return first


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--authorization-reference", required=True)
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="read one password line from stdin; the caller must confirm it separately",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not is_server_mode():
        print("administrator recovery requires MAX_SERVER_MODE=1", file=sys.stderr)
        return 2
    try:
        require_jwt_secret()
        require_database_url()
        reference = args.authorization_reference.strip()
        if not reference or len(reference) > 200 or not reference.isprintable():
            raise ValueError("authorization reference must be non-empty and printable")
        email = args.email.strip().lower()
        if not email:
            raise ValueError("email must be non-empty")
        if db_pg.get_admin_by_email(email) is None:
            raise ValueError("admin account not found")
        password = _read_password(stdin=args.password_stdin)
        if len(password.encode("utf-8")) < 8:
            raise ValueError("password must be at least 8 bytes")
        if len(password.encode("utf-8")) > 72:
            raise ValueError("password must be at most 72 bytes")

        # Invalidate all existing JWTs before changing the hash. If the DB
        # update fails, the conservative outcome is a forced re-login rather
        # than a password change with still-valid old sessions.
        auth_epoch.write_epoch(reference)
        user_id = db_pg.update_admin_password(email, auth.hash_password(password))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"administrator recovery failed: {exc}", file=sys.stderr)
        return 1

    print(f"administrator password updated for user {user_id}; existing JWT sessions invalidated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
