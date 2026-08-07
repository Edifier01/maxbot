"""P1: auth rate limit middleware."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def auth_mw(monkeypatch):
    monkeypatch.setenv("AUTH_RATE_LIMIT", "3")
    monkeypatch.setenv("AUTH_RATE_WINDOW_SEC", "60")
    monkeypatch.setattr("app.middleware.is_server_mode", lambda: True)
    from app.middleware import AuthRateLimitMiddleware

    mw = AuthRateLimitMiddleware(app=MagicMock())
    mw._counters.clear()
    return mw


def _request(path: str = "/api/auth/login", ip: str = "203.0.113.1") -> MagicMock:
    req = MagicMock()
    req.method = "POST"
    req.url.path = path
    req.client = MagicMock()
    req.client.host = ip
    return req


def test_auth_rate_limit_allows_under_cap(auth_mw):
    async def run():
        call_next = AsyncMock(return_value="ok")
        for _ in range(3):
            assert await auth_mw.dispatch(_request(), call_next) == "ok"
        call_next.assert_awaited()

    asyncio.run(run())


def test_auth_rate_limit_blocks_over_cap(auth_mw):
    async def run():
        call_next = AsyncMock(return_value="ok")
        for _ in range(3):
            await auth_mw.dispatch(_request(), call_next)
        resp = await auth_mw.dispatch(_request(), call_next)
        assert resp.status_code == 429

    asyncio.run(run())


def test_auth_rate_limit_skipped_off_server_mode(auth_mw, monkeypatch):
    monkeypatch.setattr("app.middleware.is_server_mode", lambda: False)

    async def run():
        call_next = AsyncMock(return_value="ok")
        for _ in range(10):
            assert await auth_mw.dispatch(_request(), call_next) == "ok"

    asyncio.run(run())
