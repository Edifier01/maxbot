"""Phase 3: settings scope, WS auth, Celery tenant header."""

from __future__ import annotations

import asyncio
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tenant import tenant_scope


def test_settings_tenant_vs_global_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)

    import main as m

    monkeypatch.setattr(m, "ROOT", tmp_path)

    global_dir = tmp_path / "data" / "global"
    global_dir.mkdir(parents=True)
    tenant_dir = tmp_path / "data" / "tenants" / "3"
    tenant_dir.mkdir(parents=True)

    def _init_settings_db(db_path):
        with sqlite3.connect(db_path) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS settings_audit "
                "(id INTEGER PRIMARY KEY, key TEXT, old_value TEXT, new_value TEXT, "
                "changed_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )

    _init_settings_db(global_dir / "app.db")
    _init_settings_db(tenant_dir / "app.db")

    m._settings_cache.clear()

    with tenant_scope(tenant_id=3, role="user"):
        m.set_setting("auto_run", "1")
        assert m.get_setting("auto_run") == "1"

    with tenant_scope(tenant_id=3, role="user"):
        assert m.get_setting("auto_run") == "1"

    from app.tenant import set_context, clear_context

    set_context(role="admin", use_global_data=True)
    try:
        assert m.get_setting("auto_run") in ("", "0")
    finally:
        clear_context()

    m._settings_cache.clear()


def test_internal_token_requires_tenant_header_server_mode(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "svc-test-token")
    monkeypatch.setattr("app.middleware.is_server_mode", lambda: True)
    monkeypatch.setattr("app.middleware.INTERNAL_SERVICE_TOKEN", "svc-test-token")
    monkeypatch.setattr("app.middleware.db_pg.get_tenant", lambda tid: {"id": tid})

    fake_main = MagicMock()
    fake_main._try_legacy_unlock = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "main", fake_main)

    from app.middleware import ServerAuthMiddleware

    mw = ServerAuthMiddleware(app=MagicMock())

    async def run_no_header():
        req = MagicMock()
        req.method = "POST"
        req.url.path = "/api/campaign/start"
        req.headers = {"Authorization": "Bearer svc-test-token"}
        req.cookies = {}
        call_next = AsyncMock(return_value="ok")
        resp = await mw.dispatch(req, call_next)
        assert resp.status_code == 403
        call_next.assert_not_awaited()

    asyncio.run(run_no_header())

    async def run_with_header():
        req = MagicMock()
        req.method = "POST"
        req.url.path = "/api/campaign/start"
        req.headers = {
            "Authorization": "Bearer svc-test-token",
            "X-Tenant-Id": "5",
        }
        req.cookies = {}
        call_next = AsyncMock(return_value="ok")
        resp = await mw.dispatch(req, call_next)
        assert resp == "ok"
        call_next.assert_awaited_once()

    asyncio.run(run_with_header())


def test_celery_enqueue_accepts_tenant_id():
    import inspect

    from celery_worker import enqueue_campaign_start

    sig = inspect.signature(enqueue_campaign_start)
    assert "tenant_id" in sig.parameters
