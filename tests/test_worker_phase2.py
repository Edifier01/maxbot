"""Worker monolith phase 2: explicit deps, send/pacing in campaign_send."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from app.tenant import tenant_scope


def test_campaign_worker_has_no_lazy_m_bridge():
    src = Path(__file__).resolve().parents[1] / "app" / "campaign_worker.py"
    text = src.read_text(encoding="utf-8")
    assert "def _m(" not in text
    assert "_m()" not in text


def test_campaign_send_importable():
    from app.campaign_send import compute_send_delay_sec, send_with_retry, sleep_send_delay

    delay, kind = compute_send_delay_sec()
    assert delay > 0
    assert kind in ("normal", "short", "long")
    assert callable(send_with_retry)
    assert callable(sleep_send_delay)


def test_campaign_facade_proxy():
    from app.campaign_facade import main

    assert main.APP_VERSION


def test_send_with_retry_success_writes_sent(tmp_path, monkeypatch):
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

    async def ok(*_a, **_k):
        return 1

    monkeypatch.setattr(m, "_with_client", ok)
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
            result = await send_with_retry(prow, grow, "hi", 0, 0, 0, 0)
            assert result is True

    asyncio.run(_run())

    with tenant_scope(tenant_id=6, role="user"):
        with m._conn() as c:
            status = c.execute(
                "SELECT status FROM send_log WHERE profile_id=7"
            ).fetchone()[0]
        assert status == "sent"
