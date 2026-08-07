"""Role plan percent split + campaign_scale_v18 migration."""

from __future__ import annotations

import sqlite3

import antiban_core
import main as m


def test_split_role_counts_30_accounts():
    s, a, q = antiban_core.split_role_counts(
        30, skip_percent=40, active_percent=30, quiet_percent=30
    )
    assert (s, a, q) == (12, 9, 9)


def test_split_role_counts_sum_and_non_skip():
    for n in (1, 10, 30, 100):
        s, a, q = antiban_core.split_role_counts(
            n, skip_percent=40, active_percent=30, quiet_percent=30
        )
        assert s + a + q == n
        if n > 0:
            assert s < n


def test_campaign_scale_v18_migration(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(m, "DATA", data)
    monkeypatch.setattr(m, "DB_PATH", data / "app.db")
    m._settings_cache.clear()
    m.init_db()
    with m._conn() as c:
        c.execute("UPDATE settings SET value='60' WHERE key='delay_min_sec'")
        c.execute("UPDATE settings SET value='180' WHERE key='delay_max_sec'")
        c.execute("UPDATE settings SET value='20' WHERE key='day_skip_percent'")
        c.execute("UPDATE settings SET value='4' WHERE key='break_after_n'")
        c.execute("UPDATE settings SET value='10' WHERE key='long_pause_chance'")
        c.execute("DELETE FROM settings WHERE key='role_active_percent'")
        c.execute("DELETE FROM settings WHERE key='role_quiet_percent'")
        c.execute("DELETE FROM settings WHERE key='campaign_scale_v18'")
        m._migrate_antiban_defaults(c)
    m._settings_cache.clear()
    assert m.get_setting("delay_min_sec") == "5"
    assert m.get_setting("delay_max_sec") == "15"
    assert m.get_setting("day_skip_percent") == "40"
    assert m.get_setting("role_active_percent") == "30"
    assert m.get_setting("role_quiet_percent") == "30"
    assert m.get_setting("break_after_n") == "8"
    assert m.get_setting("long_pause_chance") == "3"


def test_migration_skips_custom_delay(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(m, "DATA", data)
    monkeypatch.setattr(m, "DB_PATH", data / "app.db")
    m._settings_cache.clear()
    m.init_db()
    with m._conn() as c:
        c.execute("UPDATE settings SET value='45' WHERE key='delay_min_sec'")
        c.execute("DELETE FROM settings WHERE key='campaign_scale_v18'")
        m._migrate_antiban_defaults(c)
    m._settings_cache.clear()
    assert m.get_setting("delay_min_sec") == "45"


def test_defaults_factory():
    assert m.DEFAULTS["delay_min_sec"] == "5"
    assert m.DEFAULTS["daily_limit_max"] == "10"
    assert m.DEFAULTS["role_active_percent"] == "30"
    assert m.DEFAULTS["day_skip_percent"] == "40"
