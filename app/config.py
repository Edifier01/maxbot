"""Конфигурация серверного режима (MAX_SERVER_MODE=1)."""

from __future__ import annotations

import os
import secrets
from urllib.parse import urlsplit

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


def webhook_url_allowed(value: str) -> bool:
    """Allow explicit HTTPS webhook hosts only; unset allowlist disables webhooks."""
    try:
        url = urlsplit(value.strip())
        host = (url.hostname or "").lower()
        port = url.port
    except ValueError:
        return False
    allowed = {
        item.strip().lower()
        for item in os.environ.get("WEBHOOK_ALLOWED_HOSTS", "").split(",")
        if item.strip()
    }
    return (
        url.scheme == "https"
        and host in allowed
        and not url.username
        and not url.password
        and port in (None, 443)
    )


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


def _is_test_mode() -> bool:
    return os.environ.get("MAX_TEST", "").strip().lower() in ("1", "true", "yes")


def _placeholder_or_empty(value: str) -> bool:
    v = (value or "").strip()
    return not v or v.lower().startswith("change-me")


def require_production_secrets() -> None:
    """Server mode: reject empty or change-me* secrets. Skipped when MAX_TEST=1."""
    if not is_server_mode() or _is_test_mode():
        return
    bad = [
        name
        for name, value in (
            ("JWT_SECRET", os.environ.get("JWT_SECRET", "")),
            ("ADMIN_PASSWORD", os.environ.get("ADMIN_PASSWORD", "")),
            ("INTERNAL_SERVICE_TOKEN", os.environ.get("INTERNAL_SERVICE_TOKEN", "")),
        )
        if _placeholder_or_empty(value)
    ]
    if bad:
        raise RuntimeError(
            "MAX_SERVER_MODE=1: задайте реальные секреты (не пустые и не change-me*): "
            + ", ".join(bad)
        )


def is_server_mode() -> bool:
    return MAX_SERVER_MODE


def require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError(
            "MAX_SERVER_MODE=1 требует DATABASE_URL (PostgreSQL). "
            "См. .env.example"
        )
    return DATABASE_URL
