"""Per-tenant worker runtime and startup reset tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.campaign_runtime import REGISTRY, RUNTIME
from app.tenant import tenant_scope


def test_runtime_registry_isolates_tenants():
    REGISTRY.reset_test()
    rt1 = REGISTRY.worker_for(1)
    rt2 = REGISTRY.worker_for(2)
    rt1.consecutive_errors[10] = 5
    assert rt2.consecutive_errors == {}
    assert REGISTRY.worker_for(1) is rt1


def test_runtime_proxy_uses_tenant_context():
    REGISTRY.reset_test()
    with tenant_scope(tenant_id=7, role="user"):
        RUNTIME.consecutive_errors[3] = 1
    with tenant_scope(tenant_id=8, role="user"):
        assert RUNTIME.consecutive_errors == {}
    REGISTRY.reset_test()


def test_tenant_sqlite_paths_and_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)

    tenants = tmp_path / "data" / "tenants"
    (tenants / "1").mkdir(parents=True)
    (tenants / "2").mkdir(parents=True)
    db1 = tenants / "1" / "app.db"
    db2 = tenants / "2" / "app.db"

    for db in (db1, db2):
        with sqlite3.connect(db) as c:
            c.executescript(
                """
                CREATE TABLE campaigns (
                    id INTEGER PRIMARY KEY, status TEXT, finished_at TEXT, reason TEXT
                );
                CREATE TABLE queue_state (id INTEGER PRIMARY KEY, running INTEGER);
                INSERT INTO campaigns (id, status) VALUES (1, 'running');
                INSERT INTO queue_state (id, running) VALUES (1, 1);
                """
            )

    import main as m

    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._tenant_sqlite_paths()
    paths = m._tenant_sqlite_paths()
    assert db1 in paths
    assert db2 in paths

    m._sqlite_reset_running_campaigns(db1)
    with sqlite3.connect(db1) as c:
        row = c.execute("SELECT status FROM campaigns WHERE id=1").fetchone()
        qs = c.execute("SELECT running FROM queue_state WHERE id=1").fetchone()
    assert row[0] == "stopped"
    assert qs[0] == 0

    with sqlite3.connect(db2) as c:
        row = c.execute("SELECT status FROM campaigns WHERE id=1").fetchone()
    assert row[0] == "running"


def test_worker_start_captures_tenant_context(tmp_path, monkeypatch):
    """Worker task restores tenant context after HTTP scope ends."""
    import asyncio

    REGISTRY.reset_test()
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import main as m

    monkeypatch.setattr(m, "ROOT", tmp_path)
    tenant_dir = tmp_path / "data" / "tenants" / "5"
    tenant_dir.mkdir(parents=True)
    db_path = tenant_dir / "app.db"

    with sqlite3.connect(db_path) as c:
        c.executescript(
            """
            CREATE TABLE queue_state (id INTEGER PRIMARY KEY, running INTEGER,
                profile_idx INTEGER DEFAULT 0, message_idx INTEGER DEFAULT 0,
                group_idx INTEGER DEFAULT 0);
            INSERT INTO queue_state (id, running) VALUES (1, 0);
            CREATE TABLE campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT,
                started_at TEXT, finished_at TEXT, reason TEXT, config_snapshot TEXT
            );
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
            """
        )

    captured: list[int | None] = []

    async def fake_worker_loop():
        from app.tenant import get_tenant_id

        captured.append(get_tenant_id())
        raise asyncio.CancelledError

    import app.campaign_worker as cw

    monkeypatch.setattr(cw, "worker_loop", fake_worker_loop)
    monkeypatch.setattr(m, "_pool_size", lambda: 1)
    monkeypatch.setattr(m, "_preflight_group_proxies", lambda: asyncio.sleep(0))
    monkeypatch.setattr(m, "load_message_pool", lambda: ["hi"])
    monkeypatch.setattr(m, "_message_pick_mode", lambda: "round_robin")
    monkeypatch.setattr(m, "_begin_campaign", lambda **_: None)

    async def _run_test():
        with tenant_scope(tenant_id=5, role="user", user_id=1):
            await m._start_worker(record_campaign=False)
        rt = REGISTRY.worker_for(5)
        assert rt.worker_task is not None
        with pytest.raises(asyncio.CancelledError):
            await rt.worker_task
        assert captured == [5]

    asyncio.run(_run_test())
    REGISTRY.reset_test()
