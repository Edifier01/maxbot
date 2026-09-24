"""A30 legacy queue state must fail closed instead of rebuilding silently."""

from __future__ import annotations

import sqlite3

import pytest


def _connection(raw: str) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE queue_state (id INTEGER PRIMARY KEY, message_idx INTEGER, message_bag TEXT)"
    )
    connection.execute(
        "INSERT INTO queue_state (id, message_idx, message_bag) VALUES (1, 1, ?)",
        (raw,),
    )
    return connection


@pytest.mark.parametrize("raw", ["not-json", '{"item": 1}', "[0, 0]", "[-1]"])
def test_corrupt_legacy_bag_is_not_rebuilt_or_replayed(monkeypatch, raw: str) -> None:
    import main as m
    from app.campaign_queue import MessageBagIntegrityError, _ensure_message_bag

    connection = _connection(raw)
    monkeypatch.setattr(m, "_message_pick_mode", lambda: "random_norepeat")
    monkeypatch.setattr(m, "_campaign_goal", lambda: "message_pool")
    try:
        with pytest.raises(MessageBagIntegrityError):
            _ensure_message_bag(connection, 2)
        assert connection.execute(
            "SELECT message_bag FROM queue_state WHERE id=1"
        ).fetchone()[0] == raw
    finally:
        connection.close()
