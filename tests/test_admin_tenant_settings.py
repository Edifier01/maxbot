"""Admin per-tenant worker_pool_size (no PostgreSQL required)."""

from __future__ import annotations

import importlib

from app.tenant import tenant_scope


def _setup_server_main(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-min-32-characters-long")

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    return m


def _init_tenant_db(main_mod, tenant_id: int) -> None:
    from app.tenant_init import ensure_tenant_data

    ensure_tenant_data(main_mod.ROOT, tenant_id)
    with tenant_scope(tenant_id=tenant_id, role="user"):
        if not main_mod._db_path().exists():
            main_mod.init_db()


def test_admin_tenant_settings_sync(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_tenant_db(m, 5)
    monkeypatch.setattr(
        "app.routes_admin.db_pg.get_tenant",
        lambda tid: {"tenant_id": tid} if tid == 5 else None,
    )

    from app.routes_admin import (
        _set_tenant_worker_pool_size_sync,
        _tenant_worker_pool_size_sync,
    )

    assert _tenant_worker_pool_size_sync(5) == 1
    old = _set_tenant_worker_pool_size_sync(5, 3)
    assert old == 1
    assert _tenant_worker_pool_size_sync(5) == 3


def test_user_put_settings_ignores_worker_pool_size(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_tenant_db(m, 5)

    with tenant_scope(tenant_id=5, role="admin"):
        m.set_setting("worker_pool_size", "4")

    from app.routes_models import SettingsIn
    from app.routes_settings import update_settings
    from app.tenant import clear_context, set_context

    set_context(user_id=1, tenant_id=5, role="user")
    try:
        import asyncio

        asyncio.run(update_settings(SettingsIn(worker_pool_size=8)))
    finally:
        clear_context()

    with tenant_scope(tenant_id=5, role="admin"):
        assert m.get_setting("worker_pool_size") == "4"


def test_admin_put_settings_allows_worker_pool_size(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_tenant_db(m, 5)

    from app.routes_models import SettingsIn
    from app.routes_settings import update_settings
    from app.tenant import clear_context, set_context

    set_context(user_id=1, tenant_id=5, role="admin")
    try:
        import asyncio

        asyncio.run(update_settings(SettingsIn(worker_pool_size=2)))
    finally:
        clear_context()

    with tenant_scope(tenant_id=5, role="admin"):
        assert m.get_setting("worker_pool_size") == "2"
