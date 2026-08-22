"""Regression tests for findings from the production audit."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def test_delete_orphan_profile_is_atomic_and_preserves_linked_profile():
    from app.routes_groups import _delete_orphan_profile

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE profiles (id INTEGER PRIMARY KEY);
        CREATE TABLE group_profiles (group_id INTEGER, profile_id INTEGER);
        CREATE TABLE antiban_state (profile_id INTEGER);
        INSERT INTO profiles VALUES (1), (2);
        INSERT INTO group_profiles VALUES (10, 2);
        INSERT INTO antiban_state VALUES (1), (2);
        """
    )

    assert _delete_orphan_profile(conn, 1) is True
    assert _delete_orphan_profile(conn, 2) is False
    assert [row[0] for row in conn.execute("SELECT id FROM profiles ORDER BY id")] == [2]
    assert [row[0] for row in conn.execute("SELECT profile_id FROM antiban_state ORDER BY profile_id")] == [2]


def test_server_log_fails_closed_instead_of_returning_global_log(monkeypatch):
    from app.routes_dashboard import get_log

    monkeypatch.setattr("app.routes_dashboard.m._is_server_mode", lambda: True)
    monkeypatch.setattr("app.routes_dashboard.m._conn", MagicMock(side_effect=sqlite3.Error("broken")))
    monkeypatch.setattr("app.routes_dashboard.m._log", ["other tenant secret"])

    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_log())
    assert exc.value.status_code == 503
    assert "other tenant secret" not in str(exc.value.detail)


def test_exit_impersonation_revokes_current_impersonation_jwt(monkeypatch):
    from app.routes_auth import exit_impersonation

    monkeypatch.setattr("app.routes_auth.is_server_mode", lambda: True)
    request = MagicMock()
    request.cookies = {"max_admin_token": "admin", "max_token": "imp"}
    request.url.scheme = "https"
    request.headers = {}
    admin_payload = {"sub": "9", "role": "admin", "jti": "admin-jti"}
    imp_payload = {"sub": "9", "role": "admin", "tenant_id": 2, "imp": True, "jti": "imp-jti"}

    with patch("app.routes_auth.auth.decode_token", side_effect=[admin_payload, imp_payload]), patch(
        "app.routes_auth.auth.validate_token_session", return_value=None
    ), patch("app.routes_auth.db_pg.get_user_by_id", return_value={"id": 9, "role": "admin", "tenant_id": None, "email": "a@b.c"}), patch(
        "app.routes_auth.db_pg.subscription_info", return_value={"active": False}
    ), patch(
        "app.routes_auth.db_pg.revoke_token"
    ) as revoke, patch("app.routes_auth.auth.token_expires_at", return_value="expiry"), patch(
        "app.routes_auth.auth.invalidate_session_cache"
    ) as invalidate:
        response = asyncio.run(exit_impersonation(request))

    assert response.status_code == 200
    revoke.assert_called_once_with("imp-jti", "expiry")
    invalidate.assert_called_once_with("imp-jti")


def test_server_sqlite_connection_is_scoped_per_thread(tmp_path, monkeypatch):
    from app import sqlite_backend

    fake_main = SimpleNamespace(
        DB_BACKEND="sqlite",
        ROOT=tmp_path,
        DATA=tmp_path,
        _is_server_mode=lambda: True,
        _resolve_data_dir=lambda: tmp_path,
    )
    sqlite_backend.reset_connections()
    monkeypatch.setattr(sqlite_backend, "_main", lambda: fake_main)

    main_conn = sqlite_backend._conn()
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker_conn = pool.submit(sqlite_backend._conn).result()

    assert worker_conn is not main_conn
    assert len(sqlite_backend._tenant_db_conns) == 2
    sqlite_backend.reset_connections()


def test_applied_postgres_migration_checksum_mismatch_fails_closed():
    from app.db_pg import _migration_done

    cursor = MagicMock()
    cursor.fetchone.return_value = {"checksum": "old-digest"}
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        _migration_done(cursor, "001_saas_core", "new-digest")


def test_sqlite_integrity_triggers_repair_and_enforce_relations():
    from app.sqlite_backend import _install_integrity_triggers

    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE profiles (id INTEGER PRIMARY KEY);
        CREATE TABLE groups (id INTEGER PRIMARY KEY);
        CREATE TABLE group_profiles (group_id INTEGER, profile_id INTEGER);
        CREATE TABLE send_log (id INTEGER PRIMARY KEY, profile_id INTEGER, group_id INTEGER);
        CREATE TABLE antiban_state (profile_id INTEGER);
        INSERT INTO profiles VALUES (1);
        INSERT INTO groups VALUES (10);
        INSERT INTO group_profiles VALUES (999, 999);
        INSERT INTO send_log VALUES (1, 999, 999);
        INSERT INTO antiban_state VALUES (999);
        """
    )
    _install_integrity_triggers(conn)

    assert conn.execute("SELECT COUNT(*) FROM group_profiles").fetchone()[0] == 0
    assert conn.execute("SELECT profile_id, group_id FROM send_log").fetchone() == (None, None)
    assert conn.execute("SELECT COUNT(*) FROM antiban_state").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError, match="foreign key violation"):
        conn.execute("INSERT INTO group_profiles VALUES (10, 999)")
    conn.execute("INSERT INTO group_profiles VALUES (10, 1)")
    conn.execute("INSERT INTO send_log VALUES (2, 1, 10)")
    conn.execute("DELETE FROM profiles WHERE id=1")
    assert conn.execute("SELECT COUNT(*) FROM group_profiles").fetchone()[0] == 0
    assert conn.execute("SELECT profile_id FROM send_log WHERE id=2").fetchone()[0] is None


def test_docker_runtime_is_multistage_and_non_root():
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
    runtime = dockerfile.split(" AS runtime", 1)[1]
    assert " AS builder" in dockerfile
    assert "pip wheel" in dockerfile
    assert "gcc" not in runtime
    assert "libffi-dev" not in runtime
    assert "USER 10001:10001" in runtime


def test_deploy_migrates_existing_data_volume_ownership():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for path in (root / "scripts" / "deploy.sh", root / ".github" / "workflows" / "deploy.yml"):
        text = path.read_text(encoding="utf-8")
        assert "--user root" in text
        assert "--entrypoint chown app -R 10001:10001 /app/data" in text


@pytest.mark.skipif(os.name != "posix", reason="production lock uses POSIX flock")
def test_second_server_instance_fails_closed_on_shared_volume(tmp_path, monkeypatch):
    from app import instance_lock

    monkeypatch.delenv("MAX_TEST", raising=False)
    instance_lock.acquire(tmp_path)
    script = (
        "from pathlib import Path; "
        "from app.instance_lock import acquire; "
        f"acquire(Path({str(tmp_path)!r}))"
    )
    env = os.environ.copy()
    env.pop("MAX_TEST", None)
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "already owns max_server_data" in result.stderr
    finally:
        instance_lock.release()


def test_server_entrypoint_always_releases_hooks():
    import inspect

    from app.main import main as server_main

    source = inspect.getsource(server_main)
    assert "finally:" in source
    assert "hooks.after_shutdown()" in source


def test_scheduler_tenant_scan_fails_closed(monkeypatch):
    from app import campaign_worker

    monkeypatch.setattr(campaign_worker.main, "_is_server_mode", lambda: True)
    monkeypatch.setattr(
        "app.db_pg.list_tenants_with_users", MagicMock(side_effect=RuntimeError("pg down"))
    )
    monkeypatch.setattr(campaign_worker.main, "append_log", MagicMock())
    assert campaign_worker.scheduler_tenant_ids() == []


def test_runtime_registry_can_drop_deleted_tenant():
    from app.campaign_runtime import RuntimeRegistry

    registry = RuntimeRegistry()
    registry.worker_for(42)
    assert registry.worker_items()
    registry.drop_worker(42)
    assert registry.worker_items() == []


def test_reconcile_tenant_quarantines_restores_or_purges(tmp_path):
    from app.tenant_init import reconcile_tenant_quarantines

    tenants = tmp_path / "data" / "tenants"
    restore = tenants / "1.deleting"
    purge = tenants / "2.deleting"
    conflict = tenants / "3.deleting"
    for path in (restore, purge, conflict, tenants / "3"):
        path.mkdir(parents=True)
        (path / "marker").write_text("x", encoding="utf-8")

    result = reconcile_tenant_quarantines(tmp_path, lambda tid: tid in (1, 3))
    assert result == {"restored": 1, "purged": 1, "conflicts": 1}
    assert (tenants / "1" / "marker").is_file()
    assert not purge.exists()
    assert conflict.exists()


def test_sqlite_uses_full_synchronous_mode(tmp_path):
    from app.sqlite_backend import _sqlite_connect

    conn = _sqlite_connect(tmp_path / "durable.db")
    try:
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
    finally:
        conn.close()


def test_subscription_revoke_stops_worker_immediately(monkeypatch):
    from app.routes_admin import revoke_subscription

    stop = AsyncMock()
    monkeypatch.setattr("app.routes_admin._require_admin", lambda: 9)
    monkeypatch.setattr("app.routes_admin.db_pg.get_tenant", lambda tid: {"id": tid})
    monkeypatch.setattr(
        "app.routes_admin.db_pg.revoke_subscription",
        lambda tenant_id, admin_id: datetime.now(timezone.utc),
    )
    monkeypatch.setattr("app.campaign_worker.stop_worker", stop)

    result = asyncio.run(revoke_subscription(42))
    assert result["active"] is False
    stop.assert_awaited_once()
    assert stop.await_args.kwargs["tenant_id"] == 42
