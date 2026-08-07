"""ProfileStatus.BANNED round-trip in per-tenant SQLite."""

from __future__ import annotations

import importlib


def _setup_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    import app.config as cfg
    import app.sqlite_backend as sqlite_backend

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    sqlite_backend.reset_connections()
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.init_db()
    return m


def test_profile_banned_status_round_trip(tmp_path, monkeypatch):
    m = _setup_db(tmp_path, monkeypatch)
    assert m.ProfileStatus.BANNED == "banned"

    phone = f"+7999{abs(hash(str(tmp_path))) % 10_000_000:07d}"
    with m._conn() as c:
        c.execute(
            "INSERT INTO profiles (phone, label, status) VALUES (?, ?, ?)",
            (phone, "banned-test", m.ProfileStatus.BANNED),
        )
        row = c.execute(
            "SELECT status FROM profiles WHERE phone=?", (phone,)
        ).fetchone()

    assert row["status"] == "banned"
    assert row["status"] == m.ProfileStatus.BANNED
