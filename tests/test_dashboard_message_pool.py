"""Dashboard must not 500 when global message_pool is missing/empty."""

from __future__ import annotations

import sqlite3


def test_load_message_pool_missing_table_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "1")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()

    global_db = tmp_path / "data" / "global" / "app.db"
    global_db.parent.mkdir(parents=True, exist_ok=True)
    # Empty SQLite file without schema (simulates early _global_conn create).
    sqlite3.connect(global_db).close()

    from app import sqlite_backend

    sqlite_backend.reset_connections()
    assert m.load_message_pool() == []
