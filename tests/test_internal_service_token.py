"""P2/P3: internal service token для Celery → campaign API."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def auth_mw(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "svc-test-token")
    monkeypatch.setattr("app.middleware.is_server_mode", lambda: True)
    monkeypatch.setattr("app.middleware.INTERNAL_SERVICE_TOKEN", "svc-test-token")
    monkeypatch.setattr("app.middleware.db_pg.get_tenant", lambda tid: {"id": tid})
    monkeypatch.setattr("app.middleware.db_pg.subscription_active", lambda tid: True)

    fake_main = MagicMock()
    fake_main._try_legacy_unlock = MagicMock()
    monkeypatch.setitem(sys.modules, "main", fake_main)

    from app.middleware import ServerAuthMiddleware

    return ServerAuthMiddleware(app=MagicMock())


def _request(
    path: str = "/api/campaign/start",
    token: str = "svc-test-token",
    tenant_id: str | None = "1",
) -> MagicMock:
    req = MagicMock()
    req.method = "POST"
    req.url.path = path
    headers = {"Authorization": f"Bearer {token}"}
    if tenant_id is not None:
        headers["X-Tenant-Id"] = tenant_id
    req.headers = headers
    req.cookies = {}
    req.client = MagicMock()
    req.client.host = "10.0.0.1"
    return req


def test_internal_token_allows_campaign_start(auth_mw):
    async def run():
        call_next = AsyncMock(return_value="ok")
        resp = await auth_mw.dispatch(_request(), call_next)
        assert resp == "ok"
        call_next.assert_awaited_once()

    asyncio.run(run())


def test_internal_token_rejects_without_tenant_id(auth_mw):
    async def run():
        call_next = AsyncMock(return_value="ok")
        resp = await auth_mw.dispatch(_request(tenant_id=None), call_next)
        assert resp.status_code == 403
        call_next.assert_not_awaited()

    asyncio.run(run())


def test_internal_token_rejects_wrong_token(auth_mw):
    async def run():
        call_next = AsyncMock(return_value="ok")
        resp = await auth_mw.dispatch(_request(token="wrong"), call_next)
        assert resp.status_code == 401
        call_next.assert_not_awaited()

    asyncio.run(run())


def test_internal_token_rejects_expired_subscription(auth_mw, monkeypatch):
    monkeypatch.setattr("app.middleware.db_pg.subscription_active", lambda tid: False)

    async def run():
        call_next = AsyncMock(return_value="ok")
        resp = await auth_mw.dispatch(_request(), call_next)
        assert resp.status_code == 402
        call_next.assert_not_awaited()

    asyncio.run(run())
