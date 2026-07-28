"""Fixtures для smoke-тестов MAX Sender (изолированный temp data/)."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def main_module(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("MAX_DATA", str(data_dir))
    monkeypatch.setenv("MAX_TEST", "1")

    import main

    main.reset_test_runtime()
    main._refresh_data_paths()
    return main


@pytest.fixture
def client(main_module):
    with TestClient(main_module.app) as test_client:
        yield test_client


def setup_vault(client, password: str = "testpass123") -> None:
    r = client.post("/api/vault/setup", json={"password": password})
    assert r.status_code == 200, r.text


def queue_indices(client) -> tuple[int, int, int]:
    body = client.get("/api/status").json()
    q = body["queue"]
    return int(q["profile_idx"]), int(q["message_idx"]), int(q["group_idx"])


def seed_campaign_db(main_module, *, profile_idx: int = 5, message_idx: int = 7, group_idx: int = 2) -> None:
    """Минимальные данные для старта кампании без PyMax."""
    today = date.today().isoformat()
    main_module.set_setting("human_rhythm_enabled", "0")
    main_module.set_setting("role_plan_enabled", "0")
    main_module.set_setting("warmup_enabled", "0")

    with main_module._conn() as c:
        for i, text in enumerate(["msg one", "msg two", "msg three"], start=1):
            c.execute(
                "INSERT INTO message_pool (text, order_index) VALUES (?, ?)",
                (text, i),
            )
        c.execute(
            "INSERT INTO groups (id, name, max_chat_id, is_active) VALUES (1, 'Test', '12345', 1)"
        )
        c.execute(
            """
            INSERT INTO profiles (
                id, phone, label, status, messages_sent_today, sent_day,
                daily_limit, daily_limit_day, created_at
            ) VALUES (1, '+79001234567', 'test', ?, 0, ?, 10, ?, datetime('now', '-30 days'))
            """,
            (main_module.ProfileStatus.ACTIVE, today, today),
        )
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, order_index, is_enabled) "
            "VALUES (1, 1, 0, 1)"
        )
        c.execute(
            """
            UPDATE queue_state
            SET running=0, profile_idx=?, message_idx=?, group_idx=?
            WHERE id=1
            """,
            (profile_idx, message_idx, group_idx),
        )


async def _idle_worker_loop() -> None:
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass


@pytest.fixture
def idle_worker(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "_worker_loop", _idle_worker_loop)
    monkeypatch.setattr(main_module, "_pool_supervisor", _idle_worker_loop)
