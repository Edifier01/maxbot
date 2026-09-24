"""T15 integration: legacy upload also publishes an immutable library version."""

from __future__ import annotations

import importlib
import sqlite3

import pytest


def test_legacy_upload_publishes_immutable_version_without_network(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_DATA", str(tmp_path / "data"))
    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE message_pool (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            order_index INTEGER NOT NULL,
            loaded_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE queue_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            profile_idx INTEGER DEFAULT 0,
            message_idx INTEGER DEFAULT 0,
            group_idx INTEGER DEFAULT 0
        );
        INSERT INTO queue_state (id) VALUES (1);
        """
    )
    monkeypatch.setattr(m, "_conn", lambda: connection)
    monkeypatch.setattr(m, "_is_server_mode", lambda: False)
    monkeypatch.setattr(m, "_reset_current_queue_for_new_pool", lambda _count: None)
    monkeypatch.setattr(m, "MESSAGES_FILE", tmp_path / "active.txt")

    assert m.save_messages_file(b"first\n# comment\nsecond\n") == 2

    from app.repositories.message_sets import MessageSetRepository

    current = MessageSetRepository(connection).current("local")
    assert current is not None
    rows = connection.execute(
        "SELECT text FROM message_set_items WHERE scope='local' ORDER BY ordinal"
    ).fetchall()
    assert [row["text"] for row in rows] == ["first", "second"]


def test_publication_failure_keeps_pool_version_and_queue_checkpoint(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_DATA", str(tmp_path / "data"))
    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    m.reset_test_runtime()
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.init_db()
    m.save_messages_file(b"old\n")
    with m._conn() as connection:
        connection.execute(
            "UPDATE queue_state SET profile_idx=3, message_idx=4, "
            "group_idx=5, message_bag=? WHERE id=1",
            ('[0]',),
        )
        before = tuple(
            connection.execute(
                "SELECT profile_idx, message_idx, group_idx, message_bag "
                "FROM queue_state WHERE id=1"
            ).fetchone()
        )

    from app.repositories.message_sets import MessageSetRepository

    def fail_publish(self, *args, **kwargs):
        raise RuntimeError("injected publication failure")

    monkeypatch.setattr(MessageSetRepository, "publish", fail_publish)
    with pytest.raises(RuntimeError, match="publication failure"):
        m.save_messages_file(b"new\n")

    assert m.load_message_pool() == ["old"]
    with m._conn() as connection:
        after = tuple(
            connection.execute(
                "SELECT profile_idx, message_idx, group_idx, message_bag "
                "FROM queue_state WHERE id=1"
            ).fetchone()
        )
        current = MessageSetRepository(connection).current("local")
    assert after == before
    assert current is not None
    assert [row["text"] for row in MessageSetRepository(connection).items(
        "local", current["version_id"]
    )] == ["old"]
