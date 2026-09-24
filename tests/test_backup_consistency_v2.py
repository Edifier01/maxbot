"""T10: live SQLite backups use the online backup API and verify integrity."""

from __future__ import annotations

import os
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


def test_backup_database_online_snapshot_during_wal_contention(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    import importlib

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    m.reset_test_runtime()
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.init_db()
    with m._conn() as connection:
        connection.execute("CREATE TABLE backup_wal_fixture (value TEXT)")
        connection.execute("INSERT INTO backup_wal_fixture(value) VALUES ('old')")

    reader = sqlite3.connect(m._db_path())
    writer = sqlite3.connect(m._db_path())
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT value FROM backup_wal_fixture").fetchall()
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute(
            "INSERT INTO backup_wal_fixture(value) VALUES ('committed-after-reader')"
        )
        writer.commit()

        destination = m.backup_database()
        assert destination is not None
        with sqlite3.connect(destination) as restored:
            assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            values = [
                row[0]
                for row in restored.execute(
                    "SELECT value FROM backup_wal_fixture ORDER BY rowid"
                )
            ]
        assert values == ["old", "committed-after-reader"]
    finally:
        reader.rollback()
        reader.close()
        writer.close()


def test_scheduled_backups_honor_custom_max_data_root(tmp_path, monkeypatch) -> None:
    previous_server_mode = os.environ.get("MAX_SERVER_MODE")
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_DATA", str(tmp_path / "custom-base"))
    import importlib

    import app.config as cfg

    importlib.reload(cfg)
    try:
        import main as m

        importlib.reload(m)
        m.reset_test_runtime()
        m.ROOT = tmp_path / "root-name-is-not-data"
        m._refresh_data_paths()

        from app.tenant_init import init_global_db, init_tenant_db

        init_global_db(m)
        init_tenant_db(m, 11)
        init_tenant_db(m, 22)

        m._run_scheduled_backups()

        data_root = tmp_path / "custom-base"
        expected = (
            data_root / "global" / "backups",
            data_root / "tenants" / "11" / "backups",
            data_root / "tenants" / "22" / "backups",
        )
        assert all(list(path.glob("app-*.db")) for path in expected)
        assert not (m.ROOT / "data" / "app.db").exists()
    finally:
        if previous_server_mode is None:
            os.environ.pop("MAX_SERVER_MODE", None)
        else:
            os.environ["MAX_SERVER_MODE"] = previous_server_mode
        importlib.reload(cfg)
