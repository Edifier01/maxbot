"""Flood wait parse + retry sleep (ADR-004: flood is not a ban)."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from types import SimpleNamespace
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

    m.reset_test_runtime()
    monkeypatch.setattr(m, "ROOT", tmp_path)
    monkeypatch.setattr(m, "_is_server_mode", lambda: True)
    tenant_dir = tmp_path / "data" / "tenants" / "8"
    tenant_dir.mkdir(parents=True)
    db_path = tenant_dir / "app.db"

    with sqlite3.connect(db_path) as c:
        c.executescript(
            """
            CREATE TABLE profiles (
                id INTEGER PRIMARY KEY, phone TEXT, status TEXT,
                last_error TEXT, fail_count INTEGER DEFAULT 0, sent_day TEXT,
                messages_sent_today INTEGER DEFAULT 0, cooldown_until TEXT
            );
                CREATE TABLE groups (
                    id INTEGER PRIMARY KEY, name TEXT, chat_id TEXT,
                    max_chat_id TEXT, invite_link TEXT, enabled INTEGER, proxy TEXT
            );
            CREATE TABLE queue_state (
                id INTEGER PRIMARY KEY, running INTEGER,
                profile_idx INTEGER DEFAULT 0, message_idx INTEGER DEFAULT 0,
                group_idx INTEGER DEFAULT 0
            );
            CREATE TABLE send_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER, group_id INTEGER, message_idx INTEGER,
                    status TEXT, error TEXT, sent_text TEXT, sent_at TEXT,
                    operation_id TEXT
            );
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO profiles (id, phone, status) VALUES (7, '+79990007777', 'active');
                INSERT INTO groups (id, name, chat_id, max_chat_id, invite_link, enabled, proxy)
                VALUES (1, 'g', 'c', '77', '', 1, 'socks5://proxy.example:1080');
            INSERT INTO queue_state (id, running) VALUES (1, 0);
            """
        )
        from app.repositories.weekly_schedule import WeeklyScheduleRepository

        weekly = WeeklyScheduleRepository(c)
        weekly.ensure_schema()
        weekly.assign_profile(7, 1)
        c.execute(
            "UPDATE profile_send_schedules SET send_weekday=? WHERE profile_id=7",
            (datetime.now().weekday(),),
        )

    calls = {"n": 0}

    class FakeGateway:
        async def check_destination(self, *, chat_id: int):
            return None

        async def send_message(self, *, chat_id: int, text: str):
            return SimpleNamespace(message_id="fixture-provider-id")

    gateway = FakeGateway()

    async def flaky(_profile_id, _phone, callback, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("flood wait 30 seconds")
        return await callback(object())

    sleep_mock = AsyncMock()
    monkeypatch.setattr(cs.asyncio, "sleep", sleep_mock)
    monkeypatch.setattr(m, "_with_client", flaky)
    monkeypatch.setattr(m, "_max_gateway", lambda _client: gateway)
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
