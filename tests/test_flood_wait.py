"""Flood wait parse + retry sleep (ADR-004: flood is not a ban)."""

from __future__ import annotations

import asyncio
import sqlite3
from unittest.mock import AsyncMock

import antiban_core
from app.tenant import tenant_scope


def test_flood_wait_seconds_parses_and_is_not_ban():
    assert antiban_core.flood_wait_seconds("flood wait 30 seconds") == 30
    assert antiban_core.flood_wait_seconds("FLOOD WAIT 1 second") == 1
    assert antiban_core.flood_wait_seconds("connection timeout") is None
    assert not antiban_core.is_ban_error("flood wait 30 seconds")


def test_send_with_retry_sleeps_flood_wait(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import main as m
    import app.campaign_send as cs
    from app.campaign_send import send_with_retry

    monkeypatch.setattr(m, "ROOT", tmp_path)
    tenant_dir = tmp_path / "data" / "tenants" / "8"
    tenant_dir.mkdir(parents=True)
    db_path = tenant_dir / "app.db"

    with sqlite3.connect(db_path) as c:
        c.executescript(
            """
            CREATE TABLE profiles (
                id INTEGER PRIMARY KEY, phone TEXT, status TEXT,
                last_error TEXT, fail_count INTEGER DEFAULT 0, sent_day TEXT,
                messages_sent_today INTEGER DEFAULT 0
            );
            CREATE TABLE groups (
                id INTEGER PRIMARY KEY, name TEXT, chat_id TEXT, enabled INTEGER
            );
            CREATE TABLE queue_state (
                id INTEGER PRIMARY KEY, running INTEGER,
                profile_idx INTEGER DEFAULT 0, message_idx INTEGER DEFAULT 0,
                group_idx INTEGER DEFAULT 0
            );
            CREATE TABLE send_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER, group_id INTEGER, message_idx INTEGER,
                status TEXT, error TEXT, sent_text TEXT
            );
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO profiles (id, phone, status) VALUES (7, '+79990007777', 'active');
            INSERT INTO groups (id, name, chat_id, enabled) VALUES (1, 'g', 'c', 1);
            INSERT INTO queue_state (id, running) VALUES (1, 0);
            """
        )

    calls = {"n": 0}

    async def flaky(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("flood wait 30 seconds")
        return 1

    sleep_mock = AsyncMock()
    monkeypatch.setattr(cs.asyncio, "sleep", sleep_mock)
    monkeypatch.setattr(m, "_with_client", flaky)
    monkeypatch.setattr(m, "_prepare_outgoing_text", lambda t, *_a, **_k: t)
    monkeypatch.setattr(m, "_touch_worker_activity", lambda: None)
    monkeypatch.setattr(m, "_on_success", lambda _pid: None)
    monkeypatch.setattr(m, "_note_human_burst", lambda _pid: None)
    monkeypatch.setattr(m, "_metric_inc", lambda _k: None)
    monkeypatch.setattr(m, "append_log", lambda _m: None)

    profile = sqlite3.connect(db_path)
    profile.row_factory = sqlite3.Row
    with profile:
        prow = profile.execute("SELECT * FROM profiles WHERE id=7").fetchone()
        grow = profile.execute("SELECT * FROM groups WHERE id=1").fetchone()

    async def _run():
        with tenant_scope(tenant_id=8, role="user"):
            ok = await send_with_retry(prow, grow, "hi", 0, 0, 0, 0)
            assert ok is True

    asyncio.run(_run())
    delays = [c.args[0] for c in sleep_mock.await_args_list]
    assert delays, "expected a retry sleep"
    assert max(delays) >= 30
