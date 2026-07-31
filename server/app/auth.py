"""JWT и хеширование паролей."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app import db_pg
from app.config import JWT_ALGORITHM, JWT_EXPIRE_HOURS, JWT_SECRET


def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Пароль слишком длинный (максимум 72 байта)")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_token(
    user_id: int,
    *,
    tenant_id: int | None,
    role: str,
    impersonating: bool = False,
    impersonator_id: int | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    tv = db_pg.get_tenant_token_version(tenant_id) if tenant_id is not None else 0
    payload = {
        "sub": str(user_id),
        "jti": secrets.token_urlsafe(16),
        "tenant_id": tenant_id,
        "tv": tv,
        "role": role,
        "imp": impersonating,
        "imp_by": impersonator_id,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def validate_token_session(payload: dict[str, Any]) -> str | None:
    """Return error detail if session invalid, else None."""
    jti = payload.get("jti")
    if jti and db_pg.is_token_revoked(jti):
        return "Сессия отозвана"
    user_id = int(payload["sub"])
    if not db_pg.get_user_by_id(user_id):
        return "Пользователь не найден"
    tenant_id = payload.get("tenant_id")
    if tenant_id is not None:
        tenant = db_pg.get_tenant(tenant_id)
        if not tenant:
            return "Учреждение не найдено"
        if int(payload.get("tv") or 0) != int(tenant.get("token_version") or 0):
            return "Сессия отозвана"
    return None


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def token_expires_at(payload: dict[str, Any]) -> datetime:
    exp = payload.get("exp")
    if exp is None:
        return datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    return datetime.fromtimestamp(int(exp), tz=timezone.utc)


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    user = db_pg.get_user_by_email(email)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


def register_user(
    institution_name: str,
    email: str,
    password: str,
) -> dict[str, Any]:
    return db_pg.register_tenant_user(
        institution_name,
        email,
        hash_password(password),
    )
