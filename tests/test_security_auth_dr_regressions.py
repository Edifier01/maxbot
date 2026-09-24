"""Regression cases for account claims and impersonation logout."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        ({"id": 7, "role": "user", "tenant_id": None}, "Сессия отозвана"),
        ({"id": 7, "role": "admin", "tenant_id": 19}, "Сессия отозвана"),
    ],
)
def test_changed_account_role_or_tenant_revokes_old_claims(monkeypatch, user, expected):
    from app import auth

    monkeypatch.setattr("app.auth_epoch.current_epoch", lambda: 0.0)
    monkeypatch.setattr(auth.db_pg, "is_token_revoked", lambda _jti: False)
    monkeypatch.setattr(auth.db_pg, "get_user_by_id", lambda _uid: user)
    monkeypatch.setattr(auth.db_pg, "get_tenant", lambda _tid: {"token_version": 0})
    payload = {"sub": "7", "role": "admin", "tenant_id": None, "jti": "old-admin"}

    assert auth.validate_token_session(payload) == expected


def test_impersonation_logout_revokes_current_and_backup_admin_jwt(monkeypatch):
    from app import auth
    from app.routes_auth import logout

    monkeypatch.setattr("app.routes_auth.is_server_mode", lambda: True)
    tokens = {
        "imp-token": {"sub": "7", "jti": "imp-jti", "imp": True},
        "admin-token": {"sub": "7", "jti": "admin-jti", "imp": False},
    }
    monkeypatch.setattr(auth, "decode_token", lambda raw: tokens[raw])
    monkeypatch.setattr(auth, "token_expires_at", lambda _payload: "fixture-expiry")
    revoked: set[str] = set()
    monkeypatch.setattr("app.routes_auth.db_pg.revoke_token", lambda jti, _expires: revoked.add(jti))
    request = MagicMock()
    request.cookies = {"max_token": "imp-token", "max_admin_token": "admin-token"}
    request.url.scheme = "https"
    request.headers = {}

    response = asyncio.run(logout(request))

    assert response.status_code == 200
    assert revoked == {"imp-jti", "admin-jti"}


def test_cached_session_rechecks_account_claims_after_role_change(monkeypatch):
    from app import auth

    user = {"id": 7, "role": "admin", "tenant_id": None}
    monkeypatch.setattr("app.auth_epoch.current_epoch", lambda: 0.0)
    monkeypatch.setattr(auth.db_pg, "is_token_revoked", lambda _jti: False)
    monkeypatch.setattr(auth.db_pg, "get_user_by_id", lambda _uid: user)
    payload = {"sub": "7", "role": "admin", "tenant_id": None, "jti": "cached-admin"}
    auth.clear_session_cache()
    try:
        assert auth.cached_validate_token_session(payload) is None
        user["role"] = "user"
        assert auth.cached_validate_token_session(payload) == "Сессия отозвана"
    finally:
        auth.clear_session_cache()


def test_impersonation_keeps_target_tenant_while_admin_account_has_no_tenant(monkeypatch):
    from app import auth

    monkeypatch.setattr("app.auth_epoch.current_epoch", lambda: 0.0)
    monkeypatch.setattr(auth.db_pg, "is_token_revoked", lambda _jti: False)
    monkeypatch.setattr(
        auth.db_pg, "get_user_by_id", lambda _uid: {"id": 7, "role": "admin", "tenant_id": None}
    )
    monkeypatch.setattr(
        auth.db_pg, "get_tenant", lambda _tid: {"id": 19, "token_version": 0}
    )
    payload = {
        "sub": "7", "role": "admin", "tenant_id": 19, "jti": "impersonating",
        "imp": True, "imp_by": 7, "tv": 0,
    }

    assert auth.validate_token_session(payload) is None
