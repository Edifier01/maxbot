"""Dashboard must not 500 when global message_pool is missing/empty."""

from __future__ import annotations

import sqlite3


def test_load_message_pool_missing_table_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "1")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()

    global_db = tmp_path / "data" / "global" / "app.db"
    global_db.parent.mkdir(parents=True, exist_ok=True)
    # Empty SQLite file without schema (simulates early _global_conn create).
    sqlite3.connect(global_db).close()

    from app import sqlite_backend

    sqlite_backend.reset_connections()
    assert m.load_message_pool() == []


def test_dashboard_ok_with_empty_tenant(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-at-least-32-characters-long")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()

    from app import sqlite_backend
    from app.tenant import tenant_scope
    from app.tenant_init import init_global_db, init_tenant_db

    sqlite_backend.reset_connections()
    init_global_db(m)
    init_tenant_db(m, tenant_id=1)

    from app import routes_dashboard

    async def _call():
        return await routes_dashboard.dashboard()

    with tenant_scope(tenant_id=1, role="user"):
        # nest_asyncio-free: use dedicated loop for this sync test
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            data = loop.run_until_complete(_call())
        finally:
            loop.close()

    assert "counts" in data
    assert data["groups_count"] == 0
    assert data["items"] == []
