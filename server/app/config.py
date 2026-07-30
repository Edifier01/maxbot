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

_JWT_ENV = os.environ.get("JWT_SECRET", "").strip()
JWT_SECRET = _JWT_ENV or secrets.token_hex(32)
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "168") or "168")

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

INTERNAL_SERVICE_TOKEN = os.environ.get("INTERNAL_SERVICE_TOKEN", "").strip()


def require_jwt_secret() -> str:
    """Production server mode must have stable JWT_SECRET (no ephemeral fallback)."""
    secret = os.environ.get("JWT_SECRET", "").strip()
    if MAX_SERVER_MODE:
        if len(secret) < 32:
            raise RuntimeError(
                "MAX_SERVER_MODE=1 требует JWT_SECRET в окружении (≥32 символов). См. .env.example"
            )
        return secret
    if not secret:
        raise RuntimeError("JWT_SECRET не задан")
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters")
    return secret


def is_server_mode() -> bool:
    return MAX_SERVER_MODE


def require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError(
            "MAX_SERVER_MODE=1 требует DATABASE_URL (PostgreSQL). "
            "См. .env.example"
        )
    return DATABASE_URL
