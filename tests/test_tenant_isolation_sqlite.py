"""Tenant A write → Tenant B must NOT see it via _conn()."""

from __future__ import annotations

import concurrent.futures
import sqlite3
import threading

import pytest

from app.tenant import tenant_scope


def test_tenant_sqlite_profiles_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)

    import main as m

    monkeypatch.setattr(m, "ROOT", tmp_path)
    (tmp_path / "data" / "tenants" / "1").mkdir(parents=True)
    (tmp_path / "data" / "tenants" / "2").mkdir(parents=True)

    with tenant_scope(tenant_id=1, role="user"):
        m._refresh_data_paths()
        m._reset_db_conn()
        with m._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS profiles (id INTEGER PRIMARY KEY, phone TEXT)"
            )
            c.execute("INSERT INTO profiles (id, phone) VALUES (1, '+111')")

    with tenant_scope(tenant_id=2, role="user"):
        m._refresh_data_paths()
        m._reset_db_conn()
        with m._conn() as c:
            try:
                rows = c.execute("SELECT * FROM profiles").fetchall()
            except sqlite3.OperationalError:
                rows = []
        assert rows == []

    db1 = tmp_path / "data" / "tenants" / "1" / "app.db"
    db2 = tmp_path / "data" / "tenants" / "2" / "app.db"
    assert db1.is_file()
    with sqlite3.connect(db1) as c:
        assert c.execute("SELECT phone FROM profiles WHERE id=1").fetchone()[0] == "+111"
    if db2.is_file():
        with sqlite3.connect(db2) as c:
            assert c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='profiles'").fetchone() is None or c.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 0


def test_auth_sessions_scoped_by_tenant(monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import main as m

    m.reset_test_runtime()

    from app.tenant import tenant_scope

    with tenant_scope(tenant_id=1, role="user"):
        m._set_auth_step(42, "waiting_sms")
    with tenant_scope(tenant_id=2, role="user"):
        sess = m._auth_sessions.get(m._auth_session_key(42), {})
        assert sess.get("step", "idle") == "idle"
    with tenant_scope(tenant_id=1, role="user"):
        sess = m._auth_sessions.get(m._auth_session_key(42), {})
        assert sess.get("step") == "waiting_sms"


def test_status_payload_log_is_tenant_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)

    import main as m

    monkeypatch.setattr(m, "ROOT", tmp_path)
    (tmp_path / "data" / "tenants" / "1").mkdir(parents=True)
    (tmp_path / "data" / "tenants" / "2").mkdir(parents=True)
    m.reset_test_runtime()

    with tenant_scope(tenant_id=1, role="user"):
        m._refresh_data_paths()
        m._reset_db_conn()
        m.init_db()
        m.append_log("TENANT1-SECRET-LINE")

    with tenant_scope(tenant_id=2, role="user"):
        m._refresh_data_paths()
        m._reset_db_conn()
        m.init_db()
        m.append_log("TENANT2-OWN-LINE")
        payload = m._build_status_payload()
        log_text = " ".join(payload["log"])
        assert "TENANT1-SECRET-LINE" not in log_text
        assert "TENANT2-OWN-LINE" in log_text


def test_concurrent_tenant_transactions_use_distinct_connections(
    tmp_path, monkeypatch
) -> None:
    """Two server scopes must transact without sharing data or a connection."""
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)

    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.reset_test_runtime()

    for tenant_id in (1, 2):
        with tenant_scope(tenant_id=tenant_id, role="user"):
            m.init_db()

    barrier = threading.Barrier(2)

    def write_marker(tenant_id: int) -> tuple[int, str]:
        marker = f"CONCURRENT-TENANT-{tenant_id}"
        with tenant_scope(tenant_id=tenant_id, role="user"):
            connection = m._conn()
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("INSERT INTO app_log(msg) VALUES (?)", (marker,))
                barrier.wait(timeout=2)
                connection.commit()
            finally:
                if connection.in_transaction:
                    connection.rollback()
            own = connection.execute(
                "SELECT COUNT(*) FROM app_log WHERE msg=?", (marker,)
            ).fetchone()[0]
            return id(connection), str(own)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write_marker, (1, 2)))

    assert len({connection_id for connection_id, _own in results}) == 2
    assert [own for _connection_id, own in results] == ["1", "1"]
    for tenant_id, other_id in ((1, 2), (2, 1)):
        database = tmp_path / "data" / "tenants" / str(tenant_id) / "app.db"
        with sqlite3.connect(database) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM app_log WHERE msg=?",
                (f"CONCURRENT-TENANT-{tenant_id}",),
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT COUNT(*) FROM app_log WHERE msg=?",
                (f"CONCURRENT-TENANT-{other_id}",),
            ).fetchone()[0] == 0
