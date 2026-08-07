"""Ban detection taxonomy and tenant stop-all on ban (ADR-004)."""

from __future__ import annotations

import asyncio
import sqlite3
from unittest.mock import AsyncMock

import pytest

import antiban_core
from app.tenant import tenant_scope


def test_is_ban_error_taxonomy():
    assert antiban_core.is_ban_error("Account banned")
    assert antiban_core.is_ban_error("user blocked")
    assert antiban_core.is_ban_error("access restricted")
    assert antiban_core.is_ban_error("account suspended")
    assert antiban_core.is_ban_error("Пользователь заблокирован")
    assert antiban_core.is_ban_error("Аккаунт ограничен")
    assert antiban_core.is_ban_error("blocked for spam")
    assert not antiban_core.is_ban_error("flood wait 30 seconds")
    assert not antiban_core.is_ban_error("Too many requests: spam")
    assert not antiban_core.is_ban_error("connection timeout")
    assert not antiban_core.is_ban_error("")


def test_mark_profile_failed_sets_banned(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import main as m

    monkeypatch.setattr(m, "ROOT", tmp_path)
    tenant_dir = tmp_path / "data" / "tenants" / "4"
    tenant_dir.mkdir(parents=True)
    db_path = tenant_dir / "app.db"

    with sqlite3.connect(db_path) as c:
        c.executescript(
            """
            CREATE TABLE profiles (
                id INTEGER PRIMARY KEY, phone TEXT, status TEXT,
                last_error TEXT, fail_count INTEGER DEFAULT 0
            );
            INSERT INTO profiles (id, phone, status) VALUES (1, '+79990001122', 'active');
            """
        )

    with tenant_scope(tenant_id=4, role="user"):
        assert m._mark_profile_failed(1, "Account banned by MAX", is_auth_err=False)

        with m._conn() as c:
            row = c.execute(
                "SELECT status, last_error, fail_count FROM profiles WHERE id=1"
            ).fetchone()
        assert row["status"] == m.ProfileStatus.BANNED
        assert "banned" in row["last_error"].lower()
        assert row["fail_count"] == 1


def test_handle_profile_banned_stops_worker_and_auto_run(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import main as m

    monkeypatch.setattr(m, "ROOT", tmp_path)
    tenant_dir = tmp_path / "data" / "tenants" / "9"
    tenant_dir.mkdir(parents=True)
    db_path = tenant_dir / "app.db"

    with sqlite3.connect(db_path) as c:
        c.executescript(
            """
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE queue_state (id INTEGER PRIMARY KEY, running INTEGER);
            CREATE TABLE campaigns (
                id INTEGER PRIMARY KEY, status TEXT, finished_at TEXT, reason TEXT
            );
            INSERT INTO queue_state (id, running) VALUES (1, 1);
            INSERT INTO campaigns (id, status) VALUES (1, 'running');
            """
        )

    stop_mock = AsyncMock()
    monkeypatch.setattr(m, "_stop_worker", stop_mock)

    async def _run():
        with tenant_scope(tenant_id=9, role="user"):
            m.set_setting("auto_run", "1")
            await m._handle_profile_banned(3, "Account banned")

    asyncio.run(_run())

    with tenant_scope(tenant_id=9, role="user"):
        assert m.get_setting("auto_run") == "0"

    stop_mock.assert_awaited_once()
    kwargs = stop_mock.await_args.kwargs
    assert kwargs["finish_status"] == "stopped"
    assert kwargs["tenant_id"] == 9
    assert "забанен" in kwargs["reason"].lower() or "banned" in kwargs["reason"].lower()


def test_send_with_retry_triggers_ban_shutdown(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import main as m
    from app.campaign_send import send_with_retry

    monkeypatch.setattr(m, "ROOT", tmp_path)
    tenant_dir = tmp_path / "data" / "tenants" / "6"
    tenant_dir.mkdir(parents=True)
    db_path = tenant_dir / "app.db"

    with sqlite3.connect(db_path) as c:
        c.executescript(
            """
            CREATE TABLE profiles (
                id INTEGER PRIMARY KEY, phone TEXT, status TEXT,
                last_error TEXT, fail_count INTEGER DEFAULT 0, sent_day TEXT
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

    ban_handler = AsyncMock()
    monkeypatch.setattr(m, "_handle_profile_banned", ban_handler)
    monkeypatch.setattr(m, "MAX_RETRY", 1)
    monkeypatch.setattr(m, "RETRY_DELAYS", [0])

    async def boom(*_a, **_k):
        raise RuntimeError("Account banned permanently")

    monkeypatch.setattr(m, "_with_client", boom)
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
        with tenant_scope(tenant_id=6, role="user"):
            ok = await send_with_retry(prow, grow, "hi", 0, 0, 0, 0)
            assert ok is False

    asyncio.run(_run())
    ban_handler.assert_awaited_once_with(7, "Account banned permanently")

    with tenant_scope(tenant_id=6, role="user"):
        with m._conn() as c:
            status = c.execute("SELECT status FROM profiles WHERE id=7").fetchone()[0]
        assert status == m.ProfileStatus.BANNED
