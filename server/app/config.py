"""Конфигурация серверного режима (MAX_SERVER_MODE=1)."""

from __future__ import annotations

import os
import secrets

MAX_SERVER_MODE = os.environ.get("MAX_SERVER_MODE", "").strip().lower() in (
    "1",
    "true",
    "yes",
)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

JWT_SECRET = os.environ.get("JWT_SECRET", "").strip() or secrets.token_hex(32)
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "168") or "168")

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

VAULT_MASTER_PASSWORD = os.environ.get("VAULT_MASTER_PASSWORD", "").strip()


def is_server_mode() -> bool:
    return MAX_SERVER_MODE


def require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError(
            "MAX_SERVER_MODE=1 требует DATABASE_URL (PostgreSQL). "
            "См. server/.env.example"
        )
    return DATABASE_URL
