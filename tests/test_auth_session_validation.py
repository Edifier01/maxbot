"""Backlog: JWT invalid after user/tenant removed from PG."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def auth_mw(monkeypatch):
    monkeypatch.setattr("app.middleware.is_server_mode", lambda: True)
    monkeypatch.setattr("app.middleware.INTERNAL_SERVICE_TOKEN", "")
    from app import auth
    from app.middleware import ServerAuthMiddleware

    auth.clear_session_cache()
    return ServerAuthMiddleware(app=MagicMock())


def _authed_request(token: str = "jwt-token") -> MagicMock:
    req = MagicMock()
    req.method = "GET"
    req.url.path = "/api/status"
    req.headers = {}
    req.cookies = {"max_token": token}
    req.client = MagicMock()
    req.client.host = "10.0.0.1"
    return req


def test_rejects_missing_user(auth_mw):
    payload = {"sub": "99", "role": "user", "tenant_id": 1, "jti": "x", "tv": 0}

    async def run():
        with patch("app.middleware.decode_token", return_value=payload), patch(
            "app.middleware.db_pg.get_user_by_id", return_value=None
        ), patch("app.middleware.db_pg.is_token_revoked", return_value=False):
            resp = await auth_mw.dispatch(_authed_request(), AsyncMock())
            assert resp.status_code == 401
            assert "Пользователь" in resp.body.decode()

    asyncio.run(run())


def test_rejects_missing_tenant(auth_mw):
    payload = {"sub": "1", "role": "user", "tenant_id": 5, "jti": "x", "tv": 0}
    user = {"id": 1, "role": "user", "tenant_id": 5}

    async def run():
        with patch("app.middleware.decode_token", return_value=payload), patch(
            "app.middleware.db_pg.get_user_by_id", return_value=user
        ), patch("app.middleware.db_pg.get_tenant", return_value=None), patch(
            "app.middleware.db_pg.is_token_revoked", return_value=False
        ):
            resp = await auth_mw.dispatch(_authed_request(), AsyncMock())
            assert resp.status_code == 401
            assert "Учреждение" in resp.body.decode()

    asyncio.run(run())


def test_rejects_revoked_jwt_on_api_read_after_positive_cache_hit(auth_mw):
    payload = {
        "sub": "1",
        "role": "user",
        "tenant_id": 1,
        "jti": "cross-worker-revoke",
        "tv": 0,
    }
    user = {"id": 1, "role": "user", "tenant_id": 1}
    tenant = {"id": 1, "token_version": 0}
    revoked = False

    async def run():
        nonlocal revoked
        call_next = AsyncMock(return_value={"summary": "protected fixture data"})
        with (
            patch("app.middleware.decode_token", return_value=payload),
            patch("app.auth_epoch.current_epoch", return_value=0.0),
            patch("app.middleware.db_pg.is_token_revoked", side_effect=lambda _jti: revoked),
            patch("app.middleware.db_pg.get_user_by_id", return_value=user),
            patch("app.middleware.db_pg.get_tenant", return_value=tenant),
        ):
            first = await auth_mw.dispatch(_authed_request(), call_next)
            assert first == {"summary": "protected fixture data"}
            revoked = True  # Another worker commits the shared revocation row.
            second = await auth_mw.dispatch(_authed_request(), call_next)

        assert getattr(second, "status_code", None) == 401
        assert call_next.await_count == 1

    try:
        asyncio.run(run())
    finally:
        from app import auth

        auth.clear_session_cache()
