"""Backlog: JWT invalid after user/tenant removed from PG."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def auth_mw(monkeypatch):
    monkeypatch.setattr("app.middleware.is_server_mode", lambda: True)
    monkeypatch.setattr("app.middleware.INTERNAL_SERVICE_TOKEN", "")
    from app.middleware import ServerAuthMiddleware

    return ServerAuthMiddleware(app=MagicMock())


def _authed_request(token: str = "jwt-token") -> MagicMock:
    req = MagicMock()
    req.method = "GET"
    req.url.path = "/api/status"
    req.headers = {"Authorization": f"Bearer {token}"}
    req.cookies = {}
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
