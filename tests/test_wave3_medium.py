"""Wave 3 (M-1..M-5): mutation rate limit, stdout log, migration lock."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import auth_rate_limit, db_pg


@pytest.fixture
def auth_mw(monkeypatch):
    monkeypatch.setattr("app.middleware.is_server_mode", lambda: True)
    monkeypatch.setattr("app.middleware.INTERNAL_SERVICE_TOKEN", "")
    from app import auth
    from app.middleware import ServerAuthMiddleware

    auth.clear_session_cache()
    auth_rate_limit.reset_memory_limits()
    return ServerAuthMiddleware(app=MagicMock())


def _patch_request(method: str = "POST", path: str = "/api/campaign/start") -> MagicMock:
    req = MagicMock()
    req.method = method
    req.url.path = path
    req.headers = {"Authorization": "Bearer jwt-token"}
    req.cookies = {}
    req.client = MagicMock()
    req.client.host = "10.0.0.1"
    return req


def test_mutation_rate_limit_blocks_spam(auth_mw):
    payload = {"sub": "42", "role": "user", "tenant_id": 1, "jti": "m1", "tv": 0}
    user = {"id": 42, "role": "user", "tenant_id": 1}
    tenant = {"id": 1, "token_version": 0}

    async def run():
        call_next = AsyncMock(return_value="ok")
        with patch("app.middleware.decode_token", return_value=payload), patch(
            "app.middleware.cached_validate_token_session", return_value=None
        ), patch("app.middleware.db_pg.subscription_active", return_value=True):
            for _ in range(60):
                resp = await auth_mw.dispatch(_patch_request(), call_next)
                assert resp == "ok"
            resp = await auth_mw.dispatch(_patch_request(), call_next)
            assert resp.status_code == 429

    asyncio.run(run())


def test_mutation_rate_limit_skips_get(auth_mw):
    payload = {"sub": "42", "role": "user", "tenant_id": 1, "jti": "m2", "tv": 0}

    async def run():
        call_next = AsyncMock(return_value="ok")
        with patch("app.middleware.decode_token", return_value=payload), patch(
            "app.middleware.cached_validate_token_session", return_value=None
        ):
            for _ in range(100):
                resp = await auth_mw.dispatch(
                    _patch_request(method="GET", path="/api/status"), call_next
                )
                assert resp == "ok"

    asyncio.run(run())


def test_migration_lock_id_is_stable():
    assert db_pg._MIGRATION_LOCK_ID == db_pg._MIGRATION_LOCK_ID
    assert 0 <= db_pg._MIGRATION_LOCK_ID < 2**31


def test_append_log_prints_in_server_mode(monkeypatch, capsys):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")
    import importlib

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "_conn", lambda: (_ for _ in ()).throw(RuntimeError("no db")))
    m.append_log("wave3 test line")
    assert "wave3 test line" in capsys.readouterr().out
