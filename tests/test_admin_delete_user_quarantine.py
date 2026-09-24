"""Admin delete_user quarantines tenant SQLite until PostgreSQL commit."""

from __future__ import annotations

import asyncio
import importlib
from unittest.mock import AsyncMock, Mock

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


def test_delete_user_restores_tenant_dir_if_pg_fails(tmp_path, monkeypatch, caplog):
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
        raise RuntimeError("database_password=fixture-private-value")

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
    assert "fixture-private-value" not in caplog.text


def test_purge_quarantine_does_not_suppress_os_lock_error(tmp_path, monkeypatch):
    from app import routes_admin

    quarantine = tmp_path / "7.deleting"
    quarantine.mkdir()
    marker = quarantine / "locked-session"
    marker.write_text("preserve", encoding="utf-8")

    def remove(_path, *, ignore_errors=False):
        if not ignore_errors:
            raise PermissionError("fixture file lock")

    monkeypatch.setattr(routes_admin.shutil, "rmtree", remove)

    with pytest.raises(PermissionError, match="fixture file lock"):
        routes_admin._purge_quarantine(quarantine)

    assert marker.read_text(encoding="utf-8") == "preserve"


def test_delete_user_reports_locked_live_directory_before_database_delete(
    tmp_path, monkeypatch
):
    m = _setup_server_main(tmp_path, monkeypatch)
    tenant_id = 9
    live = tmp_path / "data" / "tenants" / str(tenant_id)
    quarantine = live.with_name(f"{tenant_id}.deleting")

    from app.tenant_init import ensure_tenant_data

    ensure_tenant_data(m.ROOT, tenant_id)
    marker = live / "locked-session"
    marker.write_text("preserve", encoding="utf-8")

    monkeypatch.setattr(
        "app.routes_admin.db_pg.get_tenant",
        lambda tid: {"id": tid} if tid == tenant_id else None,
    )
    monkeypatch.setattr(
        "app.routes_admin.db_pg.get_tenant_user",
        lambda tid: {"id": 1, "tenant_id": tid} if tid == tenant_id else None,
    )
    monkeypatch.setattr(
        "app.routes_admin.db_pg.bump_tenant_token_version", lambda _tid: None
    )
    delete_tenant = Mock(return_value=True)
    monkeypatch.setattr("app.routes_admin.db_pg.delete_tenant", delete_tenant)
    monkeypatch.setattr("app.campaign_worker.stop_worker", AsyncMock())

    def locked_rename(_tenant_id):
        raise PermissionError("fixture file lock")

    monkeypatch.setattr("app.routes_admin._quarantine_tenant_sqlite", locked_rename)

    from app.routes_admin import delete_user

    set_context(user_id=1, role="admin")
    try:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(delete_user(tenant_id))
    finally:
        clear_context()
        from app import sqlite_backend

        sqlite_backend.reset_connections()

    assert exc_info.value.status_code == 409
    assert "файлы" in str(exc_info.value.detail).lower()
    assert live.is_dir()
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert not quarantine.exists()
    delete_tenant.assert_not_called()


def test_delete_user_reports_locked_quarantine_after_database_delete(
    tmp_path, monkeypatch
):
    m = _setup_server_main(tmp_path, monkeypatch)
    tenant_id = 8
    live = tmp_path / "data" / "tenants" / str(tenant_id)
    quarantine = live.with_name(f"{tenant_id}.deleting")

    from app.tenant_init import ensure_tenant_data

    ensure_tenant_data(m.ROOT, tenant_id)
    marker = live / "locked-session"
    marker.write_text("preserve", encoding="utf-8")

    monkeypatch.setattr(
        "app.routes_admin.db_pg.get_tenant",
        lambda tid: {"id": tid} if tid == tenant_id else None,
    )
    monkeypatch.setattr(
        "app.routes_admin.db_pg.get_tenant_user",
        lambda tid: {"id": 1, "tenant_id": tid} if tid == tenant_id else None,
    )
    monkeypatch.setattr(
        "app.routes_admin.db_pg.bump_tenant_token_version", lambda _tid: None
    )
    monkeypatch.setattr("app.routes_admin.db_pg.delete_tenant", lambda _tid: True)
    from app import auth_rate_limit

    monkeypatch.setattr(
        auth_rate_limit,
        "clear_tenant_rate_limit_keys",
        lambda *_args: None,
    )
    monkeypatch.setattr("app.campaign_worker.stop_worker", AsyncMock())
    from app.campaign_runtime import REGISTRY

    drop_worker = Mock()
    monkeypatch.setattr(REGISTRY, "drop_worker", drop_worker)

    def locked_purge(_path):
        raise PermissionError("fixture file lock")

    monkeypatch.setattr("app.routes_admin._purge_quarantine", locked_purge)

    from app.routes_admin import delete_user

    set_context(user_id=1, role="admin")
    try:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(delete_user(tenant_id))
    finally:
        clear_context()
        from app import sqlite_backend

        sqlite_backend.reset_connections()

    assert exc_info.value.status_code == 409
    assert "карантин" in str(exc_info.value.detail).lower()
    assert not live.exists()
    assert (quarantine / "locked-session").read_text(encoding="utf-8") == "preserve"
    drop_worker.assert_called_once_with(tenant_id)
