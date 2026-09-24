"""JWT и хеширование паролей."""

from __future__ import annotations

import secrets
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app import auth_epoch, db_pg
from app.config import JWT_ALGORITHM, JWT_EXPIRE_HOURS, JWT_SECRET

# ponytail: in-process TTL shaves PG round-trips; logout/revoke must invalidate explicitly.
_session_cache: dict[str, tuple[float, str | None]] = {}
_SESSION_CACHE_TTL = 30.0
SESSION_CACHE_MAX = 4096


def _prune_session_cache(now: float | None = None) -> None:
    current = _time.monotonic() if now is None else float(now)
    expired = [key for key, (deadline, _value) in _session_cache.items() if deadline <= current]
    for key in expired:
        _session_cache.pop(key, None)
    overflow = len(_session_cache) - SESSION_CACHE_MAX
    if overflow > 0:
        oldest = sorted(_session_cache.items(), key=lambda item: item[1][0])
        for key, _value in oldest[:overflow]:
            _session_cache.pop(key, None)


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
    current_auth_epoch = auth_epoch.current_epoch()
    payload = {
        "sub": str(user_id),
        "jti": secrets.token_urlsafe(16),
        "tenant_id": tenant_id,
        "tv": tv,
        "ae": current_auth_epoch,
        "role": role,
        "imp": impersonating,
        "imp_by": impersonator_id,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def validate_token_session(payload: dict[str, Any]) -> str | None:
    """Return error detail if session invalid, else None."""
    try:
        if not auth_epoch.token_is_current(payload):
            return "Сессия требует повторной авторизации"
    except auth_epoch.AuthEpochInvalid:
        return "Сессия требует повторной авторизации"
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


def cached_validate_token_session(payload: dict[str, Any]) -> str | None:
    """Cached wrapper around validate_token_session (see _SESSION_CACHE_TTL)."""
    _prune_session_cache()
    jti = payload.get("jti")
    if jti:
        hit = _session_cache.get(jti)
        if hit and _time.monotonic() < hit[0]:
            try:
                if not auth_epoch.token_is_current(payload):
                    return "Сессия требует повторной авторизации"
            except auth_epoch.AuthEpochInvalid:
                return "Сессия требует повторной авторизации"
            if db_pg.is_token_revoked(jti):
                _session_cache.pop(jti, None)
                return "Сессия отозвана"
            return hit[1]
    result = validate_token_session(payload)
    if jti:
        _session_cache[jti] = (_time.monotonic() + _SESSION_CACHE_TTL, result)
        _prune_session_cache()
    return result


def invalidate_session_cache(jti: str) -> None:
    _session_cache.pop(jti, None)


def clear_session_cache() -> None:
    _session_cache.clear()


def session_cache_size() -> int:
    _prune_session_cache()
    return len(_session_cache)


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
