"""Tenant A write → Tenant B must NOT see it via _conn()."""

from __future__ import annotations

import sqlite3

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
