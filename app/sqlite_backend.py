"""SQLite connection pool, init, schema migrations (ADR 003 phase 3)."""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from pathlib import Path


_db_conn: sqlite3.Connection | None = None
_tenant_db_conns: dict[tuple[str, int], sqlite3.Connection] = {}
_db_lock = threading.Lock()


def _main():
    import main as m

    return m


def reset_connections() -> None:
    global _db_conn
    with _db_lock:
        for conn in list(_tenant_db_conns.values()):
            with contextlib.suppress(Exception):
                conn.close()
        _tenant_db_conns.clear()
        if _db_conn is not None:
            with contextlib.suppress(Exception):
                _db_conn.close()
            _db_conn = None


def _reset_db_conn() -> None:
    global _db_conn
    m = _main()
    if not m._is_server_mode():
        with _db_lock:
            if _db_conn is not None:
                with contextlib.suppress(Exception):
                    _db_conn.close()
                _db_conn = None
        return
    path = str(m._resolve_data_dir())
    with _db_lock:
        conns = [
            _tenant_db_conns.pop(key)
            for key in list(_tenant_db_conns)
            if key[0] == path
        ]
        for conn in conns:
            with contextlib.suppress(Exception):
                conn.close()
        if _db_conn is not None:
            with contextlib.suppress(Exception):
                _db_conn.close()
            _db_conn = None


def _sqlite_connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Connections are still scoped per thread below. Cross-thread close is
    # permitted so tenant quarantine/reset can evict every pooled connection.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


def _global_db_path() -> Path:
    return _main().ROOT / "data" / "global" / "app.db"


def _global_conn() -> sqlite3.Connection:
    path = str(_global_db_path())
    key = (path, threading.get_ident())
    with _db_lock:
        if key not in _tenant_db_conns:
            _tenant_db_conns[key] = _sqlite_connect(_global_db_path())
        return _tenant_db_conns[key]


def _db_path() -> Path:
    return _main()._resolve_data_dir() / "app.db"


def _conn() -> sqlite3.Connection:
    global _db_conn
    m = _main()
    if m.DB_BACKEND == "postgres":
        raise RuntimeError(
            "DATABASE_URL указывает на PostgreSQL, но runtime SQLite. "
            "Уберите DATABASE_URL или не задайте MAX_USE_DATABASE_URL=1."
        )
    if m._is_server_mode():
        key = (str(m._resolve_data_dir()), threading.get_ident())
        with _db_lock:
            if key not in _tenant_db_conns:
                _tenant_db_conns[key] = _sqlite_connect(_db_path())
            return _tenant_db_conns[key]
    with _db_lock:
        if _db_conn is None:
            m.DATA.mkdir(parents=True, exist_ok=True)
            _db_conn = _sqlite_connect(_db_path())
        return _db_conn


def init_db() -> None:
    from app import paths

    m = _main()
    data = m._resolve_data_dir()
    data.mkdir(parents=True, exist_ok=True)
    paths.sessions_root(data).mkdir(parents=True, exist_ok=True)
    paths.messages_file(data).parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY,
                phone TEXT NOT NULL UNIQUE,
                label TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                messages_sent_today INTEGER DEFAULT 0,
                sent_day TEXT,
                last_error TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                max_chat_id TEXT,
                invite_link TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS group_profiles (
                group_id INTEGER NOT NULL,
                profile_id INTEGER NOT NULL,
                order_index INTEGER DEFAULT 0,
                is_enabled INTEGER DEFAULT 1,
                PRIMARY KEY (group_id, profile_id)
            );
            CREATE TABLE IF NOT EXISTS message_pool (
                id INTEGER PRIMARY KEY,
                text TEXT NOT NULL,
                order_index INTEGER NOT NULL,
                loaded_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS queue_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                running INTEGER DEFAULT 0,
                profile_idx INTEGER DEFAULT 0,
                message_idx INTEGER DEFAULT 0,
                group_idx INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS send_log (
                id INTEGER PRIMARY KEY,
                profile_id INTEGER,
                group_id INTEGER,
                message_idx INTEGER,
                status TEXT,
                error TEXT DEFAULT '',
                sent_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS app_log (
                id INTEGER PRIMARY KEY,
                ts TEXT DEFAULT (datetime('now')),
                msg TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings_audit (
                id INTEGER PRIMARY KEY,
                key TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                changed_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY,
                started_at TEXT,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                messages_total INTEGER DEFAULT 0,
                messages_sent INTEGER DEFAULT 0,
                messages_failed INTEGER DEFAULT 0,
                reason TEXT DEFAULT '',
                scheduled_for TEXT,
                config_json TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS campaign_schedule (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                start_at TEXT,
                enabled INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS antiban_state (
                profile_id INTEGER PRIMARY KEY,
                burst_count INTEGER DEFAULT 0,
                break_until TEXT,
                consecutive_errors INTEGER DEFAULT 0,
                circuit_opened_at REAL
            );
            INSERT OR IGNORE INTO queue_state (id) VALUES (1);
            INSERT OR IGNORE INTO campaign_schedule (id) VALUES (1);
            """
        )
        _migrate_schema(c)
        n_settings = c.execute("SELECT COUNT(*) AS n FROM settings").fetchone()["n"]
        for k, v in m.DEFAULTS.items():
            c.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
            )
        _migrate_antiban_defaults(c)
        from app.settings_scope import (
            seed_tenant_settings_from_global,
            should_seed_tenant_pacing,
        )

        if n_settings == 0 and should_seed_tenant_pacing():
            seed_tenant_settings_from_global(c)
    m._backups_dir().mkdir(parents=True, exist_ok=True)


def _table_columns(c: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate_schema(c: sqlite3.Connection) -> None:
    # profiles.status is unconstrained TEXT (no CHECK); new values (e.g. banned) need no DDL.
    cols_p = _table_columns(c, "profiles")
    if "daily_limit" not in cols_p:
        c.execute("ALTER TABLE profiles ADD COLUMN daily_limit INTEGER")
    if "daily_limit_day" not in cols_p:
        c.execute("ALTER TABLE profiles ADD COLUMN daily_limit_day TEXT")
    if "cooldown_until" not in cols_p:
        c.execute("ALTER TABLE profiles ADD COLUMN cooldown_until TEXT")
    if "proxy" not in cols_p:
        c.execute("ALTER TABLE profiles ADD COLUMN proxy TEXT DEFAULT ''")
    if "fail_count" not in cols_p:
        c.execute("ALTER TABLE profiles ADD COLUMN fail_count INTEGER DEFAULT 0")
    cols_g = _table_columns(c, "groups")
    if "proxy" not in cols_g:
        c.execute("ALTER TABLE groups ADD COLUMN proxy TEXT DEFAULT ''")
        groups = c.execute("SELECT id FROM groups").fetchall()
        for g in groups:
            row = c.execute(
                """
                SELECT p.proxy FROM profiles p
                JOIN group_profiles gp ON gp.profile_id = p.id
                WHERE gp.group_id=? AND gp.is_enabled=1
                  AND p.proxy IS NOT NULL AND TRIM(p.proxy) != ''
                ORDER BY gp.order_index, p.id LIMIT 1
                """,
                (g["id"],),
            ).fetchone()
            if row and row["proxy"]:
                c.execute(
                    "UPDATE groups SET proxy=? WHERE id=?",
                    (row["proxy"].strip(), g["id"]),
                )
    cols_q = _table_columns(c, "queue_state")
    if "message_bag" not in cols_q:
        c.execute("ALTER TABLE queue_state ADD COLUMN message_bag TEXT DEFAULT '[]'")
    cols_gp = _table_columns(c, "group_profiles")
    if "role_day" not in cols_gp:
        c.execute("ALTER TABLE group_profiles ADD COLUMN role_day TEXT")
    if "day_role" not in cols_gp:
        c.execute("ALTER TABLE group_profiles ADD COLUMN day_role TEXT")
    if "day_order" not in cols_gp:
        c.execute("ALTER TABLE group_profiles ADD COLUMN day_order INTEGER")
    cols_sl = _table_columns(c, "send_log")
    if "sent_text" not in cols_sl:
        c.execute("ALTER TABLE send_log ADD COLUMN sent_text TEXT DEFAULT ''")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_send_log_status_sent "
        "ON send_log(status, sent_at)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_send_log_profile_group "
        "ON send_log(profile_id, group_id, status)"
    )
    _install_integrity_triggers(c)


def _install_integrity_triggers(c: sqlite3.Connection) -> None:
    """Repair legacy orphans, then enforce FK-like behavior without table rebuilds."""
    c.execute(
        "DELETE FROM group_profiles WHERE group_id NOT IN (SELECT id FROM groups) "
        "OR profile_id NOT IN (SELECT id FROM profiles)"
    )
    c.execute(
        "UPDATE send_log SET profile_id=NULL WHERE profile_id IS NOT NULL "
        "AND profile_id NOT IN (SELECT id FROM profiles)"
    )
    c.execute(
        "UPDATE send_log SET group_id=NULL WHERE group_id IS NOT NULL "
        "AND group_id NOT IN (SELECT id FROM groups)"
    )
    c.execute(
        "DELETE FROM antiban_state WHERE profile_id NOT IN (SELECT id FROM profiles)"
    )
    c.executescript(
        """
        CREATE TRIGGER IF NOT EXISTS fk_group_profiles_insert
        BEFORE INSERT ON group_profiles
        WHEN NOT EXISTS (SELECT 1 FROM groups WHERE id=NEW.group_id)
          OR NOT EXISTS (SELECT 1 FROM profiles WHERE id=NEW.profile_id)
        BEGIN
            SELECT RAISE(ABORT, 'group_profiles foreign key violation');
        END;
        CREATE TRIGGER IF NOT EXISTS fk_group_profiles_update
        BEFORE UPDATE OF group_id, profile_id ON group_profiles
        WHEN NOT EXISTS (SELECT 1 FROM groups WHERE id=NEW.group_id)
          OR NOT EXISTS (SELECT 1 FROM profiles WHERE id=NEW.profile_id)
        BEGIN
            SELECT RAISE(ABORT, 'group_profiles foreign key violation');
        END;
        CREATE TRIGGER IF NOT EXISTS fk_send_log_insert
        BEFORE INSERT ON send_log
        WHEN (NEW.profile_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM profiles WHERE id=NEW.profile_id
             ))
          OR (NEW.group_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM groups WHERE id=NEW.group_id
             ))
        BEGIN
            SELECT RAISE(ABORT, 'send_log foreign key violation');
        END;
        CREATE TRIGGER IF NOT EXISTS fk_send_log_update
        BEFORE UPDATE OF profile_id, group_id ON send_log
        WHEN (NEW.profile_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM profiles WHERE id=NEW.profile_id
             ))
          OR (NEW.group_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM groups WHERE id=NEW.group_id
             ))
        BEGIN
            SELECT RAISE(ABORT, 'send_log foreign key violation');
        END;
        CREATE TRIGGER IF NOT EXISTS cascade_group_delete
        AFTER DELETE ON groups
        BEGIN
            DELETE FROM group_profiles WHERE group_id=OLD.id;
            UPDATE send_log SET group_id=NULL WHERE group_id=OLD.id;
        END;
        CREATE TRIGGER IF NOT EXISTS cascade_profile_delete
        AFTER DELETE ON profiles
        BEGIN
            DELETE FROM group_profiles WHERE profile_id=OLD.id;
            DELETE FROM antiban_state WHERE profile_id=OLD.id;
            UPDATE send_log SET profile_id=NULL WHERE profile_id=OLD.id;
        END;
        """
    )


def _migrate_antiban_defaults(c: sqlite3.Connection) -> None:
    m = _main()
    flag = c.execute(
        "SELECT value FROM settings WHERE key='antiban_defaults_v16'"
    ).fetchone()
    if not flag:
        mapping = {
            "delay_min_sec": ("60", "180"),
            "delay_max_sec": ("180", "600"),
            "jitter_percent": ("25", "40"),
            "max_msgs_per_profile_day": ("15", "12"),
        }
        for key, (old, new) in mapping.items():
            row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            if row and row["value"] == old:
                c.execute("UPDATE settings SET value=? WHERE key=?", (new, key))
        c.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('antiban_defaults_v16', '1')"
        )
    flag17 = c.execute(
        "SELECT value FROM settings WHERE key='antiban_delays_v17'"
    ).fetchone()
    if not flag17:
        row_lo = c.execute(
            "SELECT value FROM settings WHERE key='delay_min_sec'"
        ).fetchone()
        row_hi = c.execute(
            "SELECT value FROM settings WHERE key='delay_max_sec'"
        ).fetchone()
        if row_lo and row_lo["value"] == "180":
            c.execute("UPDATE settings SET value=? WHERE key=?", ("60", "delay_min_sec"))
        if row_hi and row_hi["value"] == "600":
            c.execute("UPDATE settings SET value=? WHERE key=?", ("180", "delay_max_sec"))
        c.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('antiban_delays_v17', '1')"
        )
    flag18 = c.execute(
        "SELECT value FROM settings WHERE key='campaign_scale_v18'"
    ).fetchone()
    if not flag18:
        v18_map = {
            "delay_min_sec": ("60", "5"),
            "delay_max_sec": ("180", "15"),
            "daily_limit_max": ("12", "10"),
            "max_msgs_per_profile_day": ("12", "10"),
            "day_skip_percent": ("20", "40"),
            "short_pause_chance": ("15", "8"),
            "long_pause_chance": ("10", "3"),
            "long_pause_min_sec": ("300", "120"),
            "long_pause_max_sec": ("900", "300"),
            "break_after_n": ("4", "8"),
            "break_min_sec": ("1200", "600"),
            "break_max_sec": ("2400", "1200"),
        }
        for key, (old, new) in v18_map.items():
            row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            if row and row["value"] == old:
                c.execute("UPDATE settings SET value=? WHERE key=?", (new, key))
        for key, val in (
            ("role_active_percent", "30"),
            ("role_quiet_percent", "30"),
        ):
            row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            if not row:
                c.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)", (key, val)
                )
            elif str(row["value"]).strip() in ("", "0"):
                c.execute("UPDATE settings SET value=? WHERE key=?", (val, key))
        c.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('campaign_scale_v18', '1')"
        )
    m._settings_cache.clear()
