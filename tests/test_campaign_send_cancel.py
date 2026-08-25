"""Cancellation after a MAX acknowledgement must not requeue the message."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from app.tenant import tenant_scope


def test_cancel_after_send_persists_sent_without_requeue(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import main as m
    import app.campaign_send as campaign_send
    import app.campaign_worker as campaign_worker

    monkeypatch.setattr(m, "_is_server_mode", lambda: True)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    tenant_dir = tmp_path / "data" / "tenants" / "2"
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
                id INTEGER PRIMARY KEY, name TEXT, max_chat_id TEXT,
                invite_link TEXT DEFAULT ''
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
            INSERT INTO groups (id, name, max_chat_id) VALUES (1, 'g', '42');
            INSERT INTO queue_state (id, running) VALUES (1, 0);
            INSERT INTO settings (key, value) VALUES
                ('human_presence_enabled', '0'), ('human_texts_enabled', '0');
            """
        )

    with sqlite3.connect(db_path) as c:
        c.row_factory = sqlite3.Row
        profile = c.execute("SELECT * FROM profiles WHERE id=7").fetchone()
        group = c.execute("SELECT * FROM groups WHERE id=1").fetchone()

    sent_messages = []

    class FakeClient:
        async def get_chat(self, chat_id):
            return chat_id

        async def send_message(self, *, chat_id, text):
            sent_messages.append((chat_id, text))

    async def with_fake_client(_profile_id, _phone, fn, **_kwargs):
        return await fn(FakeClient())

    monkeypatch.setattr(m, "_with_client", with_fake_client)
    monkeypatch.setattr(m, "append_log", lambda _message: None)

    persist_send_outcome = campaign_send._persist_send_outcome
    persist_calls = 0

    def cancel_first_persist(**kwargs):
        nonlocal persist_calls
        persist_calls += 1
        if persist_calls == 1:
            raise asyncio.CancelledError
        return persist_send_outcome(**kwargs)

    monkeypatch.setattr(campaign_send, "_persist_send_outcome", cancel_first_persist)
    returned_message_indexes = []
    monkeypatch.setattr(
        campaign_worker.main,
        "_return_to_message_bag",
        lambda pool_idx: returned_message_indexes.append(pool_idx),
    )
    tracker = campaign_send.SendTracker()

    async def run_send():
        with tenant_scope(tenant_id=2, role="user"):
            await campaign_send.send_with_retry(
                profile, group, "hi", 0, 0, 0, 0, tracker=tracker
            )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_send())
    campaign_worker._maybe_return_to_bag(0, tracker)
    with tenant_scope(tenant_id=2, role="user"):
        with m._conn() as c:
            sent_statuses = [row[0] for row in c.execute("SELECT status FROM send_log")]

    assert sent_messages == [(42, "hi")]
    assert tracker.may_requeue is False
    assert sent_statuses == ["sent"]
    assert returned_message_indexes == []
