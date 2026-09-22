"""T10: live SQLite backups use the online backup API and verify integrity."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def test_backup_database_uses_sqlite_online_backup_api() -> None:
    source = Path("main.py").read_text(encoding="utf-8")
    assert "source.backup(target)" in source
    assert "shutil.copy2(_db_path(), dest)" not in source


def test_backup_database_result_passes_integrity_check(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    import importlib

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.reset_test_runtime()
    m.init_db()
    with m._conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS backup_fixture (value TEXT)")
        conn.execute("INSERT INTO backup_fixture(value) VALUES ('ok')")

    destination = m.backup_database()
    assert destination is not None
    with sqlite3.connect(destination) as restored:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.execute("SELECT value FROM backup_fixture").fetchone()[0] == "ok"
