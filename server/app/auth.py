"""JWT и хеширование паролей."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from server.app import db_pg
from server.app.config import JWT_ALGORITHM, JWT_EXPIRE_HOURS, JWT_SECRET


def hash_password(password: str) -> str:
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
    payload = {
        "sub": str(user_id),
        "tenant_id": tenant_id,
        "role": role,
        "imp": impersonating,
        "imp_by": impersonator_id,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


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
    if db_pg.get_user_by_email(email):
        raise ValueError("Email уже зарегистрирован")
    tenant_id = db_pg.create_tenant(institution_name)
    user_id = db_pg.create_user(
        email,
        hash_password(password),
        tenant_id=tenant_id,
        role="user",
    )
    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "email": email.strip().lower(),
        "role": "user",
    }
