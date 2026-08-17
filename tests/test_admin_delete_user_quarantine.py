"""Admin delete_user quarantines tenant SQLite until PostgreSQL commit."""

from __future__ import annotations

import asyncio
import importlib
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.tenant import clear_context, set_context, tenant_scope


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


def test_delete_user_restores_tenant_dir_if_pg_fails(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    tenant_id = 7
    live = tmp_path / "data" / "tenants" / str(tenant_id)
    quarantine = tmp_path / "data" / "tenants" / f"{tenant_id}.deleting"

    from app.tenant_init import ensure_tenant_data

    ensure_tenant_data(m.ROOT, tenant_id)
    with tenant_scope(tenant_id=tenant_id, role="user"):
        if not m._db_path().exists():
            m.init_db()
    marker = live / "keep.txt"
    marker.write_text("ops-data", encoding="utf-8")

    def _delete_raises(tid: int) -> bool:
        assert tid == tenant_id
        assert not live.exists()
        assert quarantine.is_dir()
        assert (quarantine / "keep.txt").read_text(encoding="utf-8") == "ops-data"
        raise RuntimeError("pg down")

    monkeypatch.setattr(
        "app.routes_admin.db_pg.get_tenant",
        lambda tid: {"id": tid} if tid == tenant_id else None,
    )
    monkeypatch.setattr(
        "app.routes_admin.db_pg.get_tenant_user",
        lambda tid: {"id": 1, "tenant_id": tid} if tid == tenant_id else None,
    )
    monkeypatch.setattr(
        "app.routes_admin.db_pg.bump_tenant_token_version",
        lambda tid: None,
    )
    monkeypatch.setattr("app.routes_admin.db_pg.delete_tenant", _delete_raises)
    monkeypatch.setattr("app.campaign_worker.stop_worker", AsyncMock())

    from app.routes_admin import delete_user
    from app import sqlite_backend

    set_context(user_id=1, role="admin")
    try:
        with pytest.raises(HTTPException) as ei:
            asyncio.run(delete_user(tenant_id))
    finally:
        clear_context()
        sqlite_backend.reset_connections()

    assert ei.value.status_code == 500
    assert "сохранен" in str(ei.value.detail).lower()
    assert live.is_dir()
    assert (live / "keep.txt").read_text(encoding="utf-8") == "ops-data"
    assert not quarantine.exists()
