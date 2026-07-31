"""FIX-007/008/009: security tail — metrics, token_version, WS auth."""

from __future__ import annotations

import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def auth_mw(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "metrics-svc-token")
    monkeypatch.setattr("app.middleware.is_server_mode", lambda: True)
    monkeypatch.setattr("app.middleware.INTERNAL_SERVICE_TOKEN", "metrics-svc-token")

    fake_main = MagicMock()
    fake_main._try_legacy_unlock = MagicMock()
    monkeypatch.setitem(sys.modules, "main", fake_main)

    from app.middleware import ServerAuthMiddleware

    return ServerAuthMiddleware(app=MagicMock())


def _request(path: str, token: str = "", method: str = "GET") -> MagicMock:
    req = MagicMock()
    req.method = method
    req.url.path = path
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req.headers = headers
    req.cookies = {}
    req.client = MagicMock()
    req.client.host = "10.0.0.1"
    return req


def test_metrics_requires_service_token(auth_mw):
    async def run():
        call_next = AsyncMock(return_value="metrics-body")
        resp = await auth_mw.dispatch(_request("/metrics"), call_next)
        assert resp.status_code == 401
        call_next.assert_not_awaited()

    asyncio.run(run())


def test_metrics_rejects_user_jwt(auth_mw):
    payload = {"sub": "1", "role": "admin", "tenant_id": None, "jti": "x", "tv": 0}

    async def run():
        call_next = AsyncMock(return_value="metrics-body")
        with patch("app.middleware.decode_token", return_value=payload):
            resp = await auth_mw.dispatch(
                _request("/metrics", token="user-jwt"), call_next
            )
        assert resp.status_code == 401
        call_next.assert_not_awaited()

    asyncio.run(run())


def test_metrics_allows_internal_service_token(auth_mw):
    async def run():
        call_next = AsyncMock(return_value="metrics-body")
        resp = await auth_mw.dispatch(
            _request("/metrics", token="metrics-svc-token"), call_next
        )
        assert resp == "metrics-body"
        call_next.assert_awaited_once()

    asyncio.run(run())


def test_token_version_mismatch_rejected(auth_mw):
    payload = {"sub": "1", "role": "user", "tenant_id": 2, "jti": "x", "tv": 0}
    user = {"id": 1, "role": "user", "tenant_id": 2}
    tenant = {"id": 2, "token_version": 1}

    async def run():
        call_next = AsyncMock(return_value="ok")
        with patch("app.middleware.decode_token", return_value=payload), patch(
            "app.middleware.db_pg.get_user_by_id", return_value=user
        ), patch("app.middleware.db_pg.get_tenant", return_value=tenant), patch(
            "app.middleware.db_pg.is_token_revoked", return_value=False
        ), patch(
            "app.middleware.db_pg.subscription_active", return_value=True
        ):
            resp = await auth_mw.dispatch(
                _request("/api/status", token="jwt"), call_next
            )
            assert resp.status_code == 401
            assert "отозвана" in resp.body.decode()
            call_next.assert_not_awaited()

    asyncio.run(run())


def test_create_token_includes_tv(monkeypatch):
    monkeypatch.setattr(
        "app.auth.db_pg.get_tenant_token_version", lambda tid: 3 if tid == 5 else 0
    )
    from app import auth

    token = auth.create_token(1, tenant_id=5, role="user")
    payload = auth.decode_token(token)
    assert payload["tv"] == 3


def test_bump_tenant_token_version_increments():
    from app import db_pg

    cur = MagicMock()
    cur.fetchone.return_value = {"token_version": 2}
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cur)
    ctx.__exit__ = MagicMock(return_value=False)

    with patch.object(db_pg, "_cursor", return_value=ctx):
        assert db_pg.bump_tenant_token_version(1) == 2


def test_ws_auth_rejects_missing_type():
    from app.routes_monitor import _authenticate_ws

    ws = AsyncMock()
    ws.receive_text = AsyncMock(return_value=json.dumps({"token": "x"}))

    async def run():
        ok = await _authenticate_ws(ws)
        assert ok is False

    asyncio.run(run())


def test_ws_auth_accepts_valid_token(monkeypatch):
    from app.routes_monitor import _authenticate_ws

    monkeypatch.setattr("app.config.is_server_mode", lambda: True)
    payload = {"sub": "1", "role": "user", "tenant_id": 2, "jti": "j", "tv": 0}

    ws = AsyncMock()
    ws.receive_text = AsyncMock(
        return_value=json.dumps({"type": "auth", "token": "good-jwt"})
    )

    fake_main = MagicMock()
    fake_main._try_legacy_unlock = MagicMock()
    monkeypatch.setitem(sys.modules, "main", fake_main)

    async def run():
        with patch("app.auth.decode_token", return_value=payload), patch(
            "app.auth.validate_token_session", return_value=None
        ), patch("app.tenant.set_context") as set_ctx:
            ok = await _authenticate_ws(ws)
            assert ok is True
            set_ctx.assert_called_once()

    asyncio.run(run())
