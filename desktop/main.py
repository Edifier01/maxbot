"""MAX local sender — ponytail MVP: one file for logic, minimal deps."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import random
import re
import shutil
import signal
import sqlite3
import ssl
import sys
import threading
import time
import webbrowser
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date, datetime, time as dt_time, timedelta, timezone
from difflib import SequenceMatcher
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

import uvicorn
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, model_validator
from starlette.middleware.base import BaseHTTPMiddleware

import antiban_core

HOST = os.environ.get("MAX_HOST", "127.0.0.1")
PORT = int(os.environ.get("MAX_PORT", "8765"))
APP_URL = f"http://{HOST}:{PORT}"
APP_VERSION = "1.13.0"


def _resolve_database_url() -> str:
    """Postgres runtime ещё не готов — не наследуем системный DATABASE_URL.

    Явное включение: MAX_USE_DATABASE_URL=1 (+ DATABASE_URL=postgresql://...).
    """
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        return ""
    use = os.environ.get("MAX_USE_DATABASE_URL", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if not use:
        return ""
    return raw


DATABASE_URL = _resolve_database_url()
REDIS_URL = os.environ.get("REDIS_URL", "").strip()
USE_CELERY = os.environ.get("USE_CELERY", "").strip() in ("1", "true", "yes")
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_RETRY = 3
RETRY_DELAYS = [5, 15, 60]
RATE_LIMIT = 180
RATE_WINDOW = 60
MAX_CONSECUTIVE_ERRORS = 5
CIRCUIT_BREAK_MINUTES = 30
WORKER_TIMEOUT = 300
PIN_HASH_PREFIX = "scrypt:"
VAULT_MAGIC = b"max-sender-v1"
BACKUP_KEEP = 10
SECRET_SETTING_KEYS = frozenset({"api_pin", "telegram_bot_token"})
DB_BACKEND = (
    "postgres"
    if DATABASE_URL.startswith(("postgres://", "postgresql://"))
    else "sqlite"
)


class ProfileStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    NEEDS_REAUTH = "needs_reauth"
    DISABLED = "disabled"


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _app_root() -> Path:
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _bundle_root() -> Path:
    if _is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


ROOT = _app_root()
STATIC = _bundle_root() / "static"


def _is_test_mode() -> bool:
    return os.environ.get("MAX_TEST", "").strip().lower() in ("1", "true", "yes")


def _is_server_mode() -> bool:
    try:
        from server.app.config import is_server_mode

        return is_server_mode()
    except ImportError:
        return False


def _resolve_data_dir() -> Path:
    override = os.environ.get("MAX_DATA", "").strip()
    if override:
        return Path(override)
    if _is_server_mode():
        from server.app.tenant import get_effective_data_dir

        return get_effective_data_dir(ROOT)
    return ROOT / "data"


def _refresh_data_paths() -> None:
    """Пересчитать пути data/ (pytest: MAX_DATA между тестами)."""
    global DATA, SESSIONS, MESSAGES_FILE, DB_PATH
    global _APP_KEY_PATH, _APP_SALT_PATH, _APP_VAULT_PATH, BACKUPS
    DATA = _resolve_data_dir()
    SESSIONS = DATA / "sessions"
    MESSAGES_FILE = DATA / "messages" / "active.txt"
    DB_PATH = DATA / "app.db"
    _APP_KEY_PATH = DATA / ".app_key"
    _APP_SALT_PATH = DATA / ".app_salt"
    _APP_VAULT_PATH = DATA / ".app_vault"
    BACKUPS = DATA / "backups"


DATA = _resolve_data_dir()
SESSIONS = DATA / "sessions"
MESSAGES_FILE = DATA / "messages" / "active.txt"
DB_PATH = DATA / "app.db"

DEFAULTS = {
    # Антибан: паузы, лимиты, один отправитель
    "delay_min_sec": "60",
    "delay_max_sec": "180",
    "max_msgs_per_profile_day": "12",  # legacy; фактический лимит — daily_limit_min/max
    "daily_limit_min": "5",
    "daily_limit_max": "12",
    "jitter_percent": "40",
    "message_pick_mode": "random_norepeat",  # random_norepeat | round_robin
    # daily_limits — пока у аккаунтов есть дневной лимит; message_pool — пока не кончится TXT
    "campaign_goal": "daily_limits",
    "warmup_enabled": "1",
    "warmup_days": "7",
    "cooldown_reauth_hours": "24",
    "cooldown_fail_hours": "2",
    "password_max_attempts": "5",
    "api_pin": "",
    "webhook_url": "",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "backup_interval_hours": "24",
    "worker_pool_size": "1",
    # Человечность A+B: живые окна, выходные, пропуск дня, роли
    "human_rhythm_enabled": "1",
    "send_windows_weekday": "9-13,16-21",
    "send_windows_weekend": "11-14,17-20",
    "day_skip_percent": "20",
    "role_plan_enabled": "1",
    "role_active_min": "5",
    "role_active_max": "10",
    "role_quiet_limit": "1",
    # Человечность C: неровные паузы, перерыв после N, разный jitter
    "human_pauses_enabled": "1",
    "short_pause_chance": "15",
    "short_pause_min_sec": "30",
    "short_pause_max_sec": "50",
    "long_pause_chance": "10",
    "long_pause_min_sec": "300",
    "long_pause_max_sec": "900",
    "break_after_n": "4",
    "break_min_sec": "1200",
    "break_max_sec": "2400",
    "jitter_morning_percent": "55",
    "jitter_evening_percent": "35",
    # Человечность D: warmup 1–2 дня + lazy days у старых
    "warmup_start_min": "1",
    "warmup_start_max": "2",
    "lazy_day_percent": "15",
    "lazy_day_factor": "0.4",
    # Человечность E: presence + тексты
    "human_presence_enabled": "1",
    "presence_history_chance": "70",
    "presence_read_chance": "40",
    "presence_react_chance": "12",
    "presence_reactions": "👍,❤️,🔥,😂",
    "presence_idle_chance": "5",
    "human_texts_enabled": "1",
    "text_dedupe_enabled": "1",
    "text_similarity_max": "0.72",
    "text_dedupe_window": "6",
    "text_length_variety": "1",
    # Sprint A: timezone, circuit, escalating cooldown
    "timezone_offset_hours": "3",
    "circuit_break_minutes": "30",
    "cooldown_fail_max_hours": "48",
    "cooldown_disable_after_fails": "8",
}

_APP_KEY_PATH = DATA / ".app_key"
_APP_SALT_PATH = DATA / ".app_salt"
_APP_VAULT_PATH = DATA / ".app_vault"
BACKUPS = DATA / "backups"

_worker_task: asyncio.Task | None = None
_watchdog_task: asyncio.Task | None = None
_scheduler_task: asyncio.Task | None = None
_backup_task: asyncio.Task | None = None
_pool_tasks: list[asyncio.Task] = []
_worker_lock = asyncio.Lock()
_claim_lock = threading.Lock()
_worker_last_activity: float = 0.0
_current_campaign_id: int | None = None
_pool_done_announced = False
_metrics: dict[str, float] = {
    "messages_sent_total": 0,
    "messages_failed_total": 0,
    "campaigns_started_total": 0,
    "campaigns_finished_total": 0,
    "worker_restarts_total": 0,
    "backups_total": 0,
}
_log: list[str] = []
_log_lock = threading.Lock()
_auth_sessions: dict[int, dict[str, Any]] = {}
_login_tasks: dict[int, asyncio.Task] = {}
_db_conn: sqlite3.Connection | None = None
_tenant_db_conns: dict[str, sqlite3.Connection] = {}
_db_lock = threading.Lock()
_settings_cache: dict[str, str] = {}
_settings_cache_lock = threading.Lock()
_rate_counters: dict[str, list[float]] = defaultdict(list)
_shutting_down = False
_consecutive_errors: dict[int, int] = {}
_circuit_opened_at: dict[int, float] = {}
_fernet: Fernet | None = None
_vault_unlocked = False
# Phase C: серия отправок и «перерыв» по аккаунту (in-memory)
_human_burst_count: dict[int, int] = {}
_human_break_until: dict[int, datetime] = {}


def reset_test_runtime() -> None:
    """Сброс in-memory состояния между pytest-тестами (MAX_TEST=1)."""
    global _db_conn, _fernet, _vault_unlocked, _worker_task, _watchdog_task
    global _scheduler_task, _backup_task, _pool_tasks, _current_campaign_id
    global _pool_done_announced, _shutting_down, _worker_last_activity
    with _db_lock:
        if _db_conn is not None:
            with contextlib.suppress(Exception):
                _db_conn.close()
            _db_conn = None
    _fernet = None
    _vault_unlocked = False
    _worker_task = None
    _watchdog_task = None
    _scheduler_task = None
    _backup_task = None
    _pool_tasks = []
    _current_campaign_id = None
    _pool_done_announced = False
    _shutting_down = False
    _worker_last_activity = 0.0
    with _settings_cache_lock:
        _settings_cache.clear()
    with _log_lock:
        _log.clear()
    _auth_sessions.clear()
    _login_tasks.clear()
    _rate_counters.clear()
    _consecutive_errors.clear()
    _circuit_opened_at.clear()
    _human_burst_count.clear()
    _human_break_until.clear()
    _metrics.update(
        {
            "messages_sent_total": 0,
            "messages_failed_total": 0,
            "campaigns_started_total": 0,
            "campaigns_finished_total": 0,
            "worker_restarts_total": 0,
            "backups_total": 0,
        }
    )


# --- DB (stdlib sqlite3; PostgreSQL schema — см. schema_pg.sql / Docker) ------


def _reset_db_conn() -> None:
    global _db_conn
    if not _is_server_mode():
        with _db_lock:
            if _db_conn is not None:
                with contextlib.suppress(Exception):
                    _db_conn.close()
                _db_conn = None
        return
    key = str(_resolve_data_dir())
    with _db_lock:
        conn = _tenant_db_conns.pop(key, None)
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()
        if _db_conn is not None:
            with contextlib.suppress(Exception):
                _db_conn.close()
            _db_conn = None


def _sqlite_connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _global_db_path() -> Path:
    return ROOT / "data" / "global" / "app.db"


def _global_conn() -> sqlite3.Connection:
    path = str(_global_db_path())
    with _db_lock:
        if path not in _tenant_db_conns:
            _tenant_db_conns[path] = _sqlite_connect(_global_db_path())
        return _tenant_db_conns[path]


def _conn() -> sqlite3.Connection:
    global _db_conn
    if DB_BACKEND == "postgres":
        raise RuntimeError(
            "DATABASE_URL указывает на PostgreSQL, но runtime SQLite. "
            "Уберите DATABASE_URL или не задайте MAX_USE_DATABASE_URL=1."
        )
    if _is_server_mode():
        _refresh_data_paths()
        key = str(_resolve_data_dir())
        with _db_lock:
            if key not in _tenant_db_conns:
                _tenant_db_conns[key] = _sqlite_connect(DB_PATH)
            return _tenant_db_conns[key]
    with _db_lock:
        if _db_conn is None:
            DATA.mkdir(parents=True, exist_ok=True)
            _db_conn = _sqlite_connect(DB_PATH)
        return _db_conn


def _metric_inc(name: str, value: float = 1) -> None:
    _metrics[name] = _metrics.get(name, 0) + value


def _pool_size() -> int:
    try:
        raw = get_setting("worker_pool_size") or os.environ.get("WORKER_POOL_SIZE", "1")
        n = int(raw)
    except Exception:
        try:
            n = int(os.environ.get("WORKER_POOL_SIZE", "1") or "1")
        except ValueError:
            n = 1
    return max(1, min(n, 32))


def init_db() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    SESSIONS.mkdir(parents=True, exist_ok=True)
    MESSAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
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
        for k, v in DEFAULTS.items():
            c.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
            )
        _migrate_antiban_defaults(c)
    BACKUPS.mkdir(parents=True, exist_ok=True)


def _table_columns(c: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate_schema(c: sqlite3.Connection) -> None:
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
        # миграция: взять прокси с первого профиля группы, у которого он задан
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


def _migrate_antiban_defaults(c: sqlite3.Connection) -> None:
    """Мягкие миграции дефолтов антибана."""
    # v16: старые MVP → широкие паузы
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
    # v17: 180/600 → 60/180 (запрос пользователя)
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
    _settings_cache.clear()


def _local_now() -> datetime:
    """Текущее «локальное» время с учётом timezone_offset_hours (по умолчанию UTC+3)."""
    try:
        offset = float(
            get_setting("timezone_offset_hours") or DEFAULTS["timezone_offset_hours"]
        )
    except Exception:
        try:
            offset = float(DEFAULTS.get("timezone_offset_hours", "3"))
        except ValueError:
            offset = 3.0
    return antiban_core.local_now(offset)


def _local_today() -> date:
    return _local_now().date()


def _load_antiban_state() -> None:
    """Восстановить burst/break/circuit из SQLite после рестарта."""
    global _human_burst_count, _human_break_until, _consecutive_errors, _circuit_opened_at
    now = _local_now()
    wall = time.time()
    with _conn() as c:
        rows = c.execute("SELECT * FROM antiban_state").fetchall()
    for row in rows:
        pid = int(row["profile_id"])
        burst = int(row["burst_count"] or 0)
        if burst > 0:
            _human_burst_count[pid] = burst
        raw_break = row["break_until"]
        if raw_break:
            try:
                until = datetime.fromisoformat(str(raw_break))
                if until.tzinfo is not None:
                    until = until.replace(tzinfo=None)
                if until > now:
                    _human_break_until[pid] = until
            except ValueError:
                pass
        errs = int(row["consecutive_errors"] or 0)
        if errs > 0:
            _consecutive_errors[pid] = errs
        opened = row["circuit_opened_at"]
        if opened is not None and errs >= MAX_CONSECUTIVE_ERRORS:
            try:
                opened_f = float(opened)
            except (TypeError, ValueError):
                continue
            # wall-clock; если срок вышел — не восстанавливаем
            mins = max(1.0, _setting_float("circuit_break_minutes", float(CIRCUIT_BREAK_MINUTES)))
            if wall - opened_f < mins * 60:
                _circuit_opened_at[pid] = opened_f
            else:
                _consecutive_errors.pop(pid, None)


def _persist_antiban_profile(profile_id: int) -> None:
    burst = _human_burst_count.get(profile_id, 0)
    until = _human_break_until.get(profile_id)
    errs = _consecutive_errors.get(profile_id, 0)
    opened = _circuit_opened_at.get(profile_id)
    if burst <= 0 and until is None and errs <= 0 and opened is None:
        with _conn() as c:
            c.execute("DELETE FROM antiban_state WHERE profile_id=?", (profile_id,))
        return
    with _conn() as c:
        c.execute(
            """
            INSERT INTO antiban_state
              (profile_id, burst_count, break_until, consecutive_errors, circuit_opened_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
              burst_count=excluded.burst_count,
              break_until=excluded.break_until,
              consecutive_errors=excluded.consecutive_errors,
              circuit_opened_at=excluded.circuit_opened_at
            """,
            (
                profile_id,
                burst,
                until.isoformat(timespec="seconds") if until else None,
                errs,
                float(opened) if opened is not None else None,
            ),
        )


def get_setting(key: str) -> str:
    with _settings_cache_lock:
        if key in _settings_cache:
            return _settings_cache[key]
    if _is_server_mode():
        conn = _global_conn()
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    else:
        with _conn() as c:
            row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    val = row["value"] if row else DEFAULTS.get(key, "")
    with _settings_cache_lock:
        _settings_cache[key] = val
    return val


def _audit_mask(key: str, value: str) -> str:
    if key in SECRET_SETTING_KEYS:
        return "***" if value else ""
    return value


def _write_settings_audit(key: str, old_value: str, new_value: str) -> None:
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO settings_audit (key, old_value, new_value) VALUES (?, ?, ?)",
                (key, _audit_mask(key, old_value), _audit_mask(key, new_value)),
            )
            c.execute(
                "DELETE FROM settings_audit WHERE id NOT IN "
                "(SELECT id FROM settings_audit ORDER BY id DESC LIMIT 1000)"
            )
    except Exception:
        pass


def set_setting(key: str, value: str) -> None:
    old = get_setting(key)
    if _is_server_mode():
        conn = _global_conn()
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
    else:
        with _conn() as c:
            c.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
    with _settings_cache_lock:
        _settings_cache[key] = value
    if old != value:
        _write_settings_audit(key, old, value)
        append_log(f"Настройка изменена: {key}")


# --- PIN (scrypt) ------------------------------------------------------------


def _hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
    key = kdf.derive(pin.encode())
    return PIN_HASH_PREFIX + base64.b64encode(salt + key).decode()


def _verify_pin(pin: str, stored: str) -> bool:
    if not stored:
        return not pin
    if stored.startswith(PIN_HASH_PREFIX):
        try:
            raw = base64.b64decode(stored[len(PIN_HASH_PREFIX) :])
            salt, key = raw[:16], raw[16:]
            kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
            kdf.verify(pin.encode(), key)
            return True
        except Exception:
            return False
    # legacy plaintext — сравнение + миграция при успехе
    return pin == stored


def _pin_is_set() -> bool:
    return bool(get_setting("api_pin").strip())


def append_log(msg: str) -> None:
    line = f"[{date.today()}] {msg}"
    with _log_lock:
        _log.append(line)
        if len(_log) > 500:
            del _log[: len(_log) - 500]
    try:
        with _conn() as c:
            c.execute("INSERT INTO app_log (msg) VALUES (?)", (line,))
            c.execute(
                "DELETE FROM app_log WHERE id NOT IN "
                "(SELECT id FROM app_log ORDER BY id DESC LIMIT 5000)"
            )
    except Exception:
        pass


def _load_log_from_db() -> None:
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT msg FROM app_log ORDER BY id DESC LIMIT 200"
            ).fetchall()
        with _log_lock:
            _log.clear()
            _log.extend(reversed([r["msg"] for r in rows]))
    except Exception:
        pass


# --- messages file -----------------------------------------------------------


def parse_messages_text(raw: str) -> list[str]:
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            lines.append(s)
    return lines


def load_message_pool() -> list[str]:
    if _is_server_mode():
        conn = _global_conn()
        rows = conn.execute(
            "SELECT text FROM message_pool ORDER BY order_index"
        ).fetchall()
    else:
        with _conn() as c:
            rows = c.execute(
                "SELECT text FROM message_pool ORDER BY order_index"
            ).fetchall()
    return [r["text"] for r in rows]


def save_messages_file(content: bytes) -> int:
    text = content.decode("utf-8-sig")
    messages = parse_messages_text(text)
    if not messages:
        raise ValueError("Файл пуст или не содержит сообщений")
    global_dir = ROOT / "data" / "global" / "messages" if _is_server_mode() else MESSAGES_FILE.parent
    global_dir.mkdir(parents=True, exist_ok=True)
    msg_file = global_dir / "active.txt" if _is_server_mode() else MESSAGES_FILE
    msg_file.write_bytes(content)
    if _is_server_mode():
        conn = _global_conn()
        conn.execute("DELETE FROM message_pool")
        conn.executemany(
            "INSERT INTO message_pool (text, order_index) VALUES (?, ?)",
            [(m, i) for i, m in enumerate(messages)],
        )
    else:
        with _conn() as c:
            c.execute("DELETE FROM message_pool")
            c.executemany(
                "INSERT INTO message_pool (text, order_index) VALUES (?, ?)",
                [(m, i) for i, m in enumerate(messages)],
            )
            c.execute(
                "UPDATE queue_state SET profile_idx=0, message_idx=0, group_idx=0 WHERE id=1"
            )
    _rebuild_message_bag(len(messages))
    return len(messages)


# --- round-robin / message bag helpers ---------------------------------------


def next_index(i: int, n: int) -> int:
    return 0 if n <= 0 else (i + 1) % n


def pick_round_robin(items: list, idx: int) -> tuple[Any | None, int]:
    """Return (item, next_idx). Skips disabled handled by caller filtering."""
    if not items:
        return None, 0
    return items[idx % len(items)], next_index(idx, len(items))


def _message_pick_mode() -> str:
    mode = (get_setting("message_pick_mode") or "random_norepeat").strip()
    if mode not in ("random_norepeat", "round_robin"):
        return "random_norepeat"
    return mode


def _campaign_goal() -> str:
    g = (get_setting("campaign_goal") or "daily_limits").strip()
    if g not in ("daily_limits", "message_pool"):
        return "daily_limits"
    return g


def _get_message_bag(c: sqlite3.Connection) -> list[int]:
    row = c.execute("SELECT message_bag FROM queue_state WHERE id=1").fetchone()
    raw = (row["message_bag"] if row else None) or "[]"
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [int(x) for x in data]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return []


def _set_message_bag(c: sqlite3.Connection, bag: list[int]) -> None:
    c.execute(
        "UPDATE queue_state SET message_bag=? WHERE id=1",
        (json.dumps(bag),),
    )


def _rebuild_message_bag(n: int | None = None) -> list[int]:
    """Перемешать индексы 0..n-1. Для random_norepeat; иначе очистить bag."""
    if n is None:
        n = len(load_message_pool())
    with _conn() as c:
        if _message_pick_mode() != "random_norepeat" or n <= 0:
            _set_message_bag(c, [])
            return []
        bag = list(range(n))
        random.shuffle(bag)
        _set_message_bag(c, bag)
        return bag


def _return_to_message_bag(pool_idx: int) -> None:
    """Вернуть индекс в колоду после неудачной отправки (random_norepeat)."""
    if _message_pick_mode() != "random_norepeat":
        return
    with _conn() as c:
        bag = _get_message_bag(c)
        if pool_idx in bag:
            return
        bag.append(pool_idx)
        random.shuffle(bag)
        _set_message_bag(c, bag)
        qs = c.execute("SELECT message_idx FROM queue_state WHERE id=1").fetchone()
        mi = max(0, int(qs["message_idx"] if qs else 0) - 1)
        c.execute("UPDATE queue_state SET message_idx=? WHERE id=1", (mi,))


def _ensure_message_bag(c: sqlite3.Connection, n: int) -> list[int]:
    """Колода оставшихся индексов. При daily_limits — при опустошении перемешиваем снова."""
    if _message_pick_mode() != "random_norepeat":
        return []
    if n <= 0:
        return []
    bag = _get_message_bag(c)
    if bag:
        return bag
    goal = _campaign_goal()
    qs = c.execute("SELECT message_idx FROM queue_state WHERE id=1").fetchone()
    mi = int(qs["message_idx"] if qs else 0)
    if goal == "message_pool":
        # один проход по пулу
        if mi >= n:
            return []
        if mi == 0:
            bag = list(range(n))
        else:
            bag = list(range(mi, n))
    else:
        # цель — лимиты аккаунтов: колода бесконечно обновляется
        bag = list(range(n))
    random.shuffle(bag)
    _set_message_bag(c, bag)
    if goal == "daily_limits" and mi > 0:
        append_log(f"Колода сообщений перемешана заново ({n} шт.)")
    return bag


def _pick_next_message(
    c: sqlite3.Connection, messages: list[str], mi: int
) -> tuple[str, int, int, bool] | None:
    """Выбрать текст.

    Returns:
      (text, pool_index, progress_next, bag_mode) или None если останавливаемся по пулу.
      progress_next — счётчик отправок кампании (message_idx).
    """
    n = len(messages)
    if n == 0:
        return None
    qs = c.execute("SELECT message_idx FROM queue_state WHERE id=1").fetchone()
    cur = int(qs["message_idx"] if qs else mi)
    if _message_pick_mode() == "random_norepeat":
        bag = _ensure_message_bag(c, n)
        if not bag:
            return None
        pos = random.randrange(len(bag))
        pool_idx = bag.pop(pos)
        _set_message_bag(c, bag)
        progress_next = cur + 1
        c.execute(
            "UPDATE queue_state SET message_idx=? WHERE id=1",
            (progress_next,),
        )
        return messages[pool_idx], pool_idx, progress_next, True
    # round_robin
    if _campaign_goal() == "message_pool" and mi >= n:
        return None
    pool_idx = mi % n
    progress_next = cur + 1
    return messages[pool_idx], pool_idx, progress_next, False


def _self_check_round_robin() -> None:
    profiles = ["A", "B", "C"]
    messages = ["M1", "M2", "M3", "M4"]
    pi, mi = 0, 0
    seq = []
    for _ in range(6):
        p, pi = pick_round_robin(profiles, pi)
        m, mi = pick_round_robin(messages, mi)
        seq.append((p, m))
    assert seq == [
        ("A", "M1"),
        ("B", "M2"),
        ("C", "M3"),
        ("A", "M4"),
        ("B", "M1"),
        ("C", "M2"),
    ]
    bag = list(range(5))
    random.shuffle(bag)
    seen: set[int] = set()
    while bag:
        i = bag.pop(random.randrange(len(bag)))
        assert i not in seen
        seen.add(i)
    assert seen == {0, 1, 2, 3, 4}
    # spintax + personalization
    rendered = _render_message(
        "{Привет|Здравствуйте}, {{label}}! {{date}}",
        {"phone": "+7999", "label": "Тест"},
    )
    assert "Тест" in rendered
    assert "{" not in rendered
    assert "|" not in rendered
    assert _text_similarity("Привет мир", "привет   мир") > 0.9
    assert _text_similarity("AAAA", "BBBB") < 0.5
    assert not _is_near_duplicate("уникальный текст xyz", ["другой текст"], 0.72)


# --- MAX client (PyMax) ------------------------------------------------------


def _session_dir(profile_id: int) -> Path:
    d = SESSIONS / str(profile_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _derive_fernet(password: str, salt: bytes) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))
    return Fernet(key)


def vault_status() -> dict[str, Any]:
    has_salt = _APP_SALT_PATH.exists()
    has_legacy = _APP_KEY_PATH.exists() and not has_salt
    return {
        "unlocked": bool(_vault_unlocked and _fernet is not None),
        "protected": has_salt,
        "legacy": has_legacy,
        "needs_setup": not has_salt and not has_legacy,
    }


def _try_legacy_unlock() -> None:
    """Обратная совместимость: plaintext .app_key без соли."""
    global _fernet, _vault_unlocked
    if _APP_SALT_PATH.exists():
        return
    if not _APP_KEY_PATH.exists():
        return
    try:
        _fernet = Fernet(_APP_KEY_PATH.read_bytes())
        _vault_unlocked = True
        append_log("Хранилище: старый ключ (.app_key). Рекомендуется защитить паролем.")
    except Exception as e:
        append_log(f"Хранилище: не удалось загрузить старый ключ: {e}")


def _get_fernet() -> Fernet:
    if _fernet is None or not _vault_unlocked:
        raise RuntimeError("Хранилище сессий заблокировано — введите пароль")
    return _fernet


def _reencrypt_all_sessions(old_f: Fernet, new_f: Fernet) -> int:
    """Перешифровать все session.db.enc со старого ключа на новый."""
    n = 0
    if not SESSIONS.exists():
        return 0
    for d in SESSIONS.iterdir():
        if not d.is_dir():
            continue
        enc = d / "session.db.enc"
        db = d / "session.db"
        if db.exists() and not enc.exists():
            try:
                enc.write_bytes(old_f.encrypt(db.read_bytes()))
                db.unlink(missing_ok=True)
            except Exception:
                continue
        if not enc.exists():
            continue
        try:
            plain = old_f.decrypt(enc.read_bytes())
            enc.write_bytes(new_f.encrypt(plain))
            n += 1
        except InvalidToken:
            continue
        except OSError:
            continue
    return n


def setup_vault(password: str) -> dict[str, Any]:
    """Первичная установка или миграция с legacy .app_key на PBKDF2."""
    global _fernet, _vault_unlocked
    if len(password) < 6:
        raise ValueError("Пароль хранилища должен быть не короче 6 символов")
    if _APP_SALT_PATH.exists():
        raise ValueError("Хранилище уже защищено — используйте разблокировку")

    DATA.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(16)
    new_f = _derive_fernet(password, salt)
    migrated = 0
    if _APP_KEY_PATH.exists():
        old_f = Fernet(_APP_KEY_PATH.read_bytes())
        migrated = _reencrypt_all_sessions(old_f, new_f)
        _APP_KEY_PATH.unlink(missing_ok=True)

    _APP_SALT_PATH.write_bytes(salt)
    _APP_VAULT_PATH.write_bytes(new_f.encrypt(VAULT_MAGIC))
    _fernet = new_f
    _vault_unlocked = True
    append_log(
        f"Хранилище защищено паролем"
        + (f" (перешифровано сессий: {migrated})" if migrated else "")
    )
    return {"ok": True, "migrated_sessions": migrated}


def unlock_vault(password: str) -> None:
    global _fernet, _vault_unlocked
    if not _APP_SALT_PATH.exists():
        raise ValueError("Сначала задайте пароль хранилища")
    salt = _APP_SALT_PATH.read_bytes()
    candidate = _derive_fernet(password, salt)
    if not _APP_VAULT_PATH.exists():
        raise ValueError("Повреждён файл хранилища (.app_vault)")
    try:
        magic = candidate.decrypt(_APP_VAULT_PATH.read_bytes())
    except InvalidToken as e:
        raise ValueError("Неверный пароль хранилища") from e
    if magic != VAULT_MAGIC:
        raise ValueError("Неверный пароль хранилища")
    _fernet = candidate
    _vault_unlocked = True
    append_log("Хранилище разблокировано")


def lock_vault() -> None:
    global _fernet, _vault_unlocked
    if _vault_unlocked:
        _encrypt_all_sessions()
    _fernet = None
    _vault_unlocked = False
    append_log("Хранилище заблокировано")


def _require_vault_unlocked() -> None:
    st = vault_status()
    if st["needs_setup"]:
        raise HTTPException(
            423,
            "Задайте пароль хранилища сессий (Настройки → Хранилище)",
        )
    if not st["unlocked"]:
        raise HTTPException(423, "Разблокируйте хранилище сессий")


def _decrypt_session(profile_id: int) -> None:
    d = _session_dir(profile_id)
    db, enc = d / "session.db", d / "session.db.enc"
    if not enc.exists() or db.exists():
        return
    try:
        db.write_bytes(_get_fernet().decrypt(enc.read_bytes()))
    except InvalidToken:
        enc.unlink(missing_ok=True)
        append_log(f"Профиль #{profile_id}: не удалось расшифровать сессию — войдите заново")
    except RuntimeError as e:
        append_log(f"Профиль #{profile_id}: {e}")
        raise


def _encrypt_session(profile_id: int) -> None:
    d = _session_dir(profile_id)
    db, enc = d / "session.db", d / "session.db.enc"
    if not db.exists():
        return
    try:
        enc.write_bytes(_get_fernet().encrypt(db.read_bytes()))
        db.unlink()
    except RuntimeError:
        # при shutdown без unlock — не трогаем plaintext (лучше чем потерять)
        pass
    except OSError as e:
        append_log(f"Профиль #{profile_id}: ошибка шифрования сессии: {e}")


def _clear_session(profile_id: int) -> None:
    d = _session_dir(profile_id)
    for name in ("session.db", "session.db.enc"):
        p = d / name
        if p.exists():
            p.unlink()


class _QueueSmsProvider:
    def __init__(self, q: asyncio.Queue[str], profile_id: int) -> None:
        self._q = q
        self._profile_id = profile_id

    async def get_code(self, phone: str) -> str:
        _set_auth_step(self._profile_id, "waiting_sms")
        append_log(f"Профиль #{self._profile_id}: введите SMS-код для {phone}")
        try:
            return await asyncio.wait_for(self._q.get(), timeout=300)
        except TimeoutError as e:
            raise TimeoutError("SMS-код не получен за 5 минут") from e


class _QueuePasswordProvider:
    def __init__(self, q: asyncio.Queue[str], profile_id: int) -> None:
        self._q = q
        self._profile_id = profile_id

    async def get_password(self, hint: str | None = None) -> str:
        _set_auth_step(self._profile_id, "waiting_cloud_password", hint or "")
        msg = f"Профиль #{self._profile_id}: нужен облачный пароль"
        if hint:
            msg += f" (подсказка: {hint})"
        append_log(msg)
        try:
            return await asyncio.wait_for(self._q.get(), timeout=300)
        except TimeoutError as e:
            raise TimeoutError("Облачный пароль не получен за 5 минут") from e


class _AppSmsAuthFlow:
    """SMS-вход: сначала облачный пароль (если MAX прислал challenge), потом токен."""

    def __init__(
        self,
        code_provider: _QueueSmsProvider,
        password_provider: _QueuePasswordProvider,
        profile_id: int,
    ) -> None:
        self.code_provider = code_provider
        self.password_provider = password_provider
        self._profile_id = profile_id

    async def authenticate(self, app) -> Any:
        from pymax.auth.models import AuthResult
        from pymax.exceptions import ApiError

        phone = app.config.phone
        if not phone:
            raise RuntimeError("Нужен номер телефона для входа по SMS")

        start = await app.api.auth.request_code(phone)
        code = await self.code_provider.get_code(phone)
        _set_auth_step(self._profile_id, "verifying_sms")
        result = await app.api.auth.send_code(start.token, code)

        has_login = bool(result.login_token)
        has_pwd = result.password_challenge is not None
        append_log(
            f"Профиль #{self._profile_id}: SMS проверен "
            f"(login_token={'да' if has_login else 'нет'}, "
            f"облачный пароль={'да' if has_pwd else 'нет'})"
        )

        if result.password_challenge:
            raise RuntimeError(
                "Аккаунт MAX требует облачный пароль — вход через панель не поддерживается"
            )
        elif result.login_token:
            token = result.login_token
        elif result.register_token:
            if not app.config.registration_config:
                raise RuntimeError("Для регистрации нового аккаунта не хватает настроек регистрации")
            reg = app.config.registration_config
            response = await app.api.auth.confirm_registration(
                first_name=reg.first_name,
                last_name=reg.last_name,
                token=result.register_token,
            )
            token = response.token
        else:
            raise RuntimeError(
                "MAX не вернул токен и не запросил облачный пароль после SMS"
            )

        if not token:
            raise RuntimeError("Ошибка входа: токен не получен")
        return AuthResult(token=token)

    async def _authenticate_with_password(
        self,
        app,
        track_id: str,
        hint: str | None,
    ) -> str:
        from pymax.exceptions import ApiError

        max_attempts = int(get_setting("password_max_attempts") or "5")
        attempts = 0
        while attempts < max_attempts:
            password = await self.password_provider.get_password(hint)
            _set_auth_step(self._profile_id, "verifying_password")
            if not password:
                continue
            attempts += 1
            try:
                response = await app.api.auth.check_password(track_id, password)
            except ApiError:
                _set_auth_step(self._profile_id, "waiting_cloud_password", hint or "")
                append_log(
                    f"Профиль #{self._profile_id}: неверный пароль "
                    f"({attempts}/{max_attempts})"
                )
                continue
            if response.error:
                _set_auth_step(self._profile_id, "waiting_cloud_password", hint or "")
                append_log(
                    f"Профиль #{self._profile_id}: неверный пароль "
                    f"({attempts}/{max_attempts})"
                )
                continue
            if response.login_token:
                return response.login_token
        raise RuntimeError(
            f"Превышен лимит попыток облачного пароля ({max_attempts})"
        )


async def _safe_stop(client) -> None:
    """ponytail: MAX иногда рвёт TLS при close — не считаем это ошибкой входа."""
    try:
        await asyncio.sleep(0.15)
        await asyncio.wait_for(client.stop(), timeout=15)
    except asyncio.TimeoutError:
        append_log("Принудительное отключение клиента (таймаут остановки)")
    except (ssl.SSLError, OSError, ConnectionError) as e:
        msg = str(e).lower()
        if "close_notify" not in msg and "application data after" not in msg:
            raise


_AUTH_STEPS_LONG = frozenset(
    {
        "connecting",
        "waiting_sms",
        "waiting_cloud_password",
        "verifying_sms",
        "verifying_password",
    }
)


async def _wait_login_done(
    profile_id: int,
    done: asyncio.Event,
    connect_timeout: float,
    auth_timeout: float,
    *,
    login_mode: bool = False,
) -> None:
    """Пока ждём SMS/пароль — длинный таймаут, иначе короткий."""
    t0 = time.monotonic()
    while not done.is_set():
        step = _auth_sessions.get(profile_id, {}).get("step", "connecting")
        if login_mode or step in _AUTH_STEPS_LONG:
            limit = auth_timeout
        else:
            limit = connect_timeout
        left = limit - (time.monotonic() - t0)
        if left <= 0:
            _set_auth_step(profile_id, "error")
            raise TimeoutError(
                "Таймаут входа. Нажмите «Войти заново», дождитесь SMS → код → OK. "
                "Облачный пароль — только если MAX запросит (☁)."
            )
        try:
            await asyncio.wait_for(done.wait(), timeout=min(left, 3))
            return
        except TimeoutError:
            continue


def _is_benign_disconnect(err: BaseException) -> bool:
    msg = str(err).lower()
    return "close_notify" in msg or "application data after" in msg


async def _with_client(
    profile_id: int,
    phone: str,
    fn,
    connect_timeout: float = 90,
    auth_timeout: float = 600,
    *,
    login_mode: bool = False,
    group_id: int | None = None,
    proxy: str | None = None,
):
    from pymax import Client, ExtraConfig

    sess = _ensure_auth_session(profile_id)
    _set_auth_step(profile_id, "connecting")
    _decrypt_session(profile_id)
    sms = _QueueSmsProvider(sess["sms_q"], profile_id)
    pwd = _QueuePasswordProvider(sess["pwd_q"], profile_id)
    if proxy is None and group_id is not None:
        proxy = _group_proxy(group_id, profile_id)
    extra_kwargs: dict[str, Any] = {"reconnect": False, "log_level": "WARNING"}
    if proxy:
        extra_kwargs["proxy"] = proxy
        host = proxy.split("@")[-1]
        append_log(
            f"Прокси группа#{group_id or '—'} / профиль#{profile_id}: {host}"
        )
    try:
        extra = ExtraConfig(**extra_kwargs)
    except TypeError:
        # старая версия pymax без proxy в ExtraConfig
        extra_kwargs.pop("proxy", None)
        extra = ExtraConfig(**extra_kwargs)
        if proxy:
            append_log("Внимание: клиент MAX не поддерживает прокси в этой конфигурации — работаем без него")
    client_kwargs: dict[str, Any] = {
        "phone": phone,
        "work_dir": str(_session_dir(profile_id)),
        "session_name": "session.db",
        "extra_config": extra,
    }
    if login_mode:
        client = Client(
            auth_flow=_AppSmsAuthFlow(sms, pwd, profile_id),
            **client_kwargs,
        )
    else:
        client = Client(
            sms_code_provider=sms,
            password_provider=pwd,
            **client_kwargs,
        )
    box: dict[str, Any] = {"err": None, "result": None}
    done = asyncio.Event()

    @client.on_start()
    async def on_start(c: Client) -> None:
        try:
            box["result"] = await fn(c)
        except Exception as e:
            box["err"] = e
        finally:
            done.set()

    async def _run() -> None:
        try:
            await client.start()
            if box["result"] is None and not client._app.started:
                box["err"] = RuntimeError("Сессия недействительна")
        except Exception as e:
            if box["result"] is None and not _is_benign_disconnect(e):
                box["err"] = box["err"] or e
        finally:
            done.set()

    task = asyncio.create_task(_run())
    try:
        await _wait_login_done(
            profile_id, done, connect_timeout, auth_timeout, login_mode=login_mode
        )
    except TimeoutError as e:
        box["err"] = e
    finally:
        await _safe_stop(client)
        _encrypt_session(profile_id)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    if box.get("err") and box.get("result") is None:
        raise box["err"]
    return box.get("result")


async def _login_max(
    profile_id: int,
    phone: str,
    fresh: bool = False,
    *,
    group_id: int | None = None,
) -> int:
    async def _check(c):
        if not c.me or not c.me.contact:
            raise RuntimeError("Вход не завершён — нет данных профиля")
        return c.me.contact.id

    if fresh:
        _clear_session(profile_id)
        sess = _ensure_auth_session(profile_id)
        _drain_queue(sess["sms_q"])
        _drain_queue(sess["pwd_q"])
        append_log(f"Профиль #{profile_id}: новый вход по SMS")

    me_id = await _with_client(
        profile_id,
        phone,
        _check,
        connect_timeout=90,
        auth_timeout=600,
        login_mode=True,
        group_id=group_id,
    )
    if me_id is None:
        raise RuntimeError("MAX не вернул профиль после входа")
    return me_id


async def resolve_chat_id(client, group: sqlite3.Row) -> str | None:
    if group["max_chat_id"]:
        return group["max_chat_id"]
    link = (group["invite_link"] or "").strip()
    if not link:
        return None
    chat = await client.resolve_group_by_link(link)
    if chat is None:
        joined = await client.join_group(link)
        chat = joined
    if chat is None:
        return None
    cid = str(chat.id)
    with _conn() as c:
        c.execute("UPDATE groups SET max_chat_id=? WHERE id=?", (cid, group["id"]))
    return cid


def _setting_truthy(key: str, default: str = "0") -> bool:
    return (get_setting(key) or default).strip().lower() in ("1", "true", "yes", "on")


def _human_rhythm_enabled() -> bool:
    return _setting_truthy("human_rhythm_enabled", "1")


def _role_plan_enabled() -> bool:
    return _human_rhythm_enabled() and _setting_truthy("role_plan_enabled", "1")


def _day_skip_percent() -> float:
    try:
        p = float(get_setting("day_skip_percent") or "0")
    except ValueError:
        p = 0.0
    return max(0.0, min(100.0, p))


def _parse_hhmm(part: str) -> tuple[int, int]:
    part = part.strip()
    if not part:
        raise ValueError("пустое время")
    if ":" in part:
        h_s, m_s = part.split(":", 1)
        return int(h_s), int(m_s)
    return int(part), 0


def _parse_send_windows(raw: str) -> list[tuple[dt_time, dt_time]]:
    """Парсит '9-13,16-21' или '09:00-13:00,16:00-21:00'."""
    windows: list[tuple[dt_time, dt_time]] = []
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk or "-" not in chunk:
            continue
        a, b = chunk.split("-", 1)
        try:
            h1, m1 = _parse_hhmm(a)
            h2, m2 = _parse_hhmm(b)
            start, end = dt_time(h1, m1), dt_time(h2, m2)
        except ValueError:
            continue
        if start < end:
            windows.append((start, end))
    return windows


def _windows_for_date(d: date) -> list[tuple[dt_time, dt_time]]:
    weekday_raw = get_setting("send_windows_weekday") or DEFAULTS["send_windows_weekday"]
    weekend_raw = get_setting("send_windows_weekend") or DEFAULTS["send_windows_weekend"]
    if d.weekday() >= 5:
        windows = _parse_send_windows(weekend_raw)
        if windows:
            return windows
    return _parse_send_windows(weekday_raw)


def _in_send_window(now: datetime | None = None) -> bool:
    """Локальное время: можно ли слать сейчас. Выкл. ритм → всегда да."""
    if not _human_rhythm_enabled():
        return True
    now = now or _local_now()
    windows = _windows_for_date(now.date())
    if not windows:
        return True
    t = now.time()
    return any(start <= t < end for start, end in windows)


def _seconds_until_next_window(now: datetime | None = None) -> float:
    if not _human_rhythm_enabled():
        return 0.0
    now = now or _local_now()
    if _in_send_window(now):
        return 0.0
    windows = _windows_for_date(now.date())
    t = now.time()
    for start, _end in windows:
        if t < start:
            target = datetime.combine(now.date(), start)
            return max(1.0, (target - now).total_seconds())
    for offset in range(1, 8):
        d = now.date() + timedelta(days=offset)
        tw = _windows_for_date(d)
        if not tw:
            continue
        target = datetime.combine(d, tw[0][0])
        return max(1.0, (target - now).total_seconds())
    return 3600.0


_last_window_wait_log: float = 0.0


async def _wait_if_outside_send_window() -> bool:
    """True = были вне окна и подождали (caller делает continue)."""
    global _last_window_wait_log
    if _in_send_window():
        return False
    wait = _seconds_until_next_window()
    mono = time.monotonic()
    if mono - _last_window_wait_log >= 300:
        mins = max(1, int(wait // 60))
        append_log(f"Вне окна отправки — пауза ~{mins} мин")
        _last_window_wait_log = mono
    chunk = min(wait, 60.0)
    end_at = time.monotonic() + chunk
    while time.monotonic() < end_at:
        _touch_worker_activity()
        left = end_at - time.monotonic()
        if left <= 0:
            break
        await asyncio.sleep(min(30.0, left))
    return True


def _ensure_group_role_plan(group_id: int) -> None:
    """Раз в день: shuffle + active/quiet/skip для группы."""
    if not _role_plan_enabled():
        return
    today = _local_today().isoformat()
    with _conn() as c:
        rows = c.execute(
            """
            SELECT gp.profile_id, gp.role_day, gp.is_enabled, p.status
            FROM group_profiles gp
            JOIN profiles p ON p.id = gp.profile_id
            WHERE gp.group_id=? AND gp.is_enabled=1 AND p.status=?
            ORDER BY gp.order_index, p.id
            """,
            (group_id, ProfileStatus.ACTIVE),
        ).fetchall()
        if not rows:
            return
        if all(r["role_day"] == today for r in rows):
            return

        ids = [int(r["profile_id"]) for r in rows]
        random.shuffle(ids)
        n = len(ids)
        skip_pct = _day_skip_percent()
        skip_n = int(round(n * skip_pct / 100.0)) if skip_pct > 0 else 0
        skip_n = max(0, min(n, skip_n))
        # не скипать всех: хотя бы один может писать
        if skip_n >= n and n > 0:
            skip_n = n - 1
        skip_ids = set(ids[:skip_n])
        remaining = [i for i in ids if i not in skip_ids]

        try:
            a_min = max(0, int(get_setting("role_active_min") or "5"))
        except ValueError:
            a_min = 5
        try:
            a_max = max(0, int(get_setting("role_active_max") or "10"))
        except ValueError:
            a_max = 10
        if a_min > a_max:
            a_min, a_max = a_max, a_min
        if not remaining:
            active_n = 0
        else:
            lo = min(a_min, len(remaining))
            hi = min(a_max, len(remaining))
            if lo > hi:
                lo, hi = hi, lo
            active_n = random.randint(lo, hi) if hi >= lo else len(remaining)

        active_ids = set(remaining[:active_n])
        quiet_ids = set(remaining[active_n:])

        # порядок отправки: только active+quiet, shuffle
        send_order = list(active_ids | quiet_ids)
        random.shuffle(send_order)
        order_map = {pid: idx for idx, pid in enumerate(send_order)}
        # skip в конец, стабильный порядок
        for i, pid in enumerate(sorted(skip_ids)):
            order_map[pid] = len(send_order) + i

        for pid in ids:
            if pid in skip_ids:
                role = "skip"
            elif pid in active_ids:
                role = "active"
            else:
                role = "quiet"
            c.execute(
                "UPDATE group_profiles SET role_day=?, day_role=?, day_order=? "
                "WHERE group_id=? AND profile_id=?",
                (today, role, order_map.get(pid, 0), group_id, pid),
            )

        g = c.execute("SELECT name FROM groups WHERE id=?", (group_id,)).fetchone()
        gname = g["name"] if g else str(group_id)
    append_log(
        f"Роли дня «{gname}»: активных={len(active_ids)} тихих={len(quiet_ids)} "
        f"пропуск={len(skip_ids)} (перемешано)"
    )


def _group_sends_today(profile_id: int, group_id: int) -> int:
    today = _local_today().isoformat()
    with _conn() as c:
        row = c.execute(
            """
            SELECT COUNT(*) n FROM send_log
            WHERE profile_id=? AND group_id=? AND status='sent'
              AND date(sent_at)=?
            """,
            (profile_id, group_id, today),
        ).fetchone()
    return int(row["n"] if row else 0)


def _profile_day_role(profile: sqlite3.Row | dict[str, Any]) -> str | None:
    try:
        role = profile["day_role"]
    except (KeyError, IndexError, TypeError):
        return None
    if role is None:
        return None
    s = str(role).strip().lower()
    return s or None


def _quiet_limit() -> int:
    try:
        return max(0, int(get_setting("role_quiet_limit") or "1"))
    except ValueError:
        return 1


def _can_send_in_group(profile: sqlite3.Row, group_id: int) -> bool:
    if _is_in_human_break(int(profile["id"])):
        return False
    if not _can_send(profile):
        return False
    role = _profile_day_role(profile)
    if role == "skip":
        return False
    if role == "quiet":
        return _group_sends_today(int(profile["id"]), group_id) < _quiet_limit()
    return True


def _human_pauses_enabled() -> bool:
    return _setting_truthy("human_pauses_enabled", "1")


def _setting_float(key: str, default: float) -> float:
    try:
        return float(get_setting(key) or str(default))
    except ValueError:
        return default


def _setting_int(key: str, default: int) -> int:
    try:
        return int(float(get_setting(key) or str(default)))
    except ValueError:
        return default


def _clamp_range(lo: float, hi: float) -> tuple[float, float]:
    return antiban_core.clamp_range(lo, hi)


def _jitter_percent_now(now: datetime | None = None) -> float:
    """Jitter % с учётом утра/вечера при human_pauses."""
    base = _setting_float("jitter_percent", 40.0)
    if not _human_pauses_enabled():
        return max(0.0, min(100.0, base))
    now = now or _local_now()
    hour = now.hour
    # утро: до 13; вечер: с 16; иначе базовый
    if hour < 13:
        j = _setting_float("jitter_morning_percent", 55.0)
    elif hour >= 16:
        j = _setting_float("jitter_evening_percent", 35.0)
    else:
        j = base
    return max(0.0, min(100.0, j))


def _compute_send_delay_sec(*, pool_scale: bool = False) -> tuple[float, str]:
    """Пауза после успешной отправки. Returns (seconds, kind).

    Логнормальное распределение (не uniform) — меньше bot-сигнатуры.
    pool_scale больше не укорачивает паузу (антибан важнее throughput).
    """
    lo = float(_setting_int("delay_min_sec", 60))
    hi = float(_setting_int("delay_max_sec", 180))
    lo, hi = _clamp_range(lo, hi)
    kind = "normal"
    if _human_pauses_enabled():
        short_ch = max(0.0, min(100.0, _setting_float("short_pause_chance", 15.0)))
        long_ch = max(0.0, min(100.0, _setting_float("long_pause_chance", 10.0)))
        # long и short не пересекаются: сначала long, иначе short, иначе normal
        roll = random.random() * 100.0
        if long_ch > 0 and roll < long_ch:
            slo = float(_setting_int("long_pause_min_sec", 300))
            shi = float(_setting_int("long_pause_max_sec", 900))
            lo, hi = _clamp_range(slo, shi)
            kind = "long"
        elif short_ch > 0 and roll < long_ch + short_ch:
            slo = float(_setting_int("short_pause_min_sec", 30))
            shi = float(_setting_int("short_pause_max_sec", 50))
            lo, hi = _clamp_range(slo, shi)
            kind = "short"
    delay = antiban_core.lognormal_delay_sec(
        lo, hi, jitter_percent=_jitter_percent_now()
    )
    # pool_scale оставлен в сигнатуре для совместимости; намеренно не ускоряет
    _ = pool_scale
    return delay, kind


async def _sleep_send_delay(*, pool_scale: bool = False) -> None:
    delay, kind = _compute_send_delay_sec(pool_scale=pool_scale)
    if kind == "long":
        append_log(f"Длинная пауза («отвлёкся»): ~{int(delay // 60)} мин")
    elif kind == "short":
        append_log(f"Короткая пауза: {int(delay)} с")
    end_at = time.monotonic() + delay
    while time.monotonic() < end_at:
        _touch_worker_activity()
        left = end_at - time.monotonic()
        if left <= 0:
            break
        await asyncio.sleep(min(30.0, left))


def _is_in_human_break(profile_id: int) -> bool:
    until = _human_break_until.get(profile_id)
    if not until:
        return False
    if _local_now() >= until:
        _human_break_until.pop(profile_id, None)
        _persist_antiban_profile(profile_id)
        return False
    return True


def _note_human_burst(profile_id: int) -> None:
    """После N отправок — перерыв 20–40 мин у аккаунта (не блокирует воркер)."""
    if not _human_pauses_enabled():
        return
    n = _setting_int("break_after_n", 4)
    if n <= 0:
        return
    burst = _human_burst_count.get(profile_id, 0) + 1
    if burst < n:
        _human_burst_count[profile_id] = burst
        _persist_antiban_profile(profile_id)
        return
    _human_burst_count[profile_id] = 0
    blo = float(_setting_int("break_min_sec", 1200))
    bhi = float(_setting_int("break_max_sec", 2400))
    blo, bhi = _clamp_range(blo, bhi)
    secs = random.uniform(blo, bhi)
    until = _local_now() + timedelta(seconds=secs)
    _human_break_until[profile_id] = until
    _persist_antiban_profile(profile_id)
    append_log(
        f"Перерыв аккаунта #{profile_id} после {n} сообщений: "
        f"~{int(secs // 60)} мин (до {until.strftime('%H:%M')})"
    )


def _active_profiles_for_group(group_id: int) -> list[sqlite3.Row]:
    if _role_plan_enabled():
        _ensure_group_role_plan(group_id)
    with _conn() as c:
        if _role_plan_enabled():
            return c.execute(
                """
                SELECT p.*, gp.day_role, gp.day_order FROM profiles p
                JOIN group_profiles gp ON gp.profile_id = p.id
                WHERE gp.group_id=? AND gp.is_enabled=1 AND p.status=?
                  AND COALESCE(gp.day_role, '') != 'skip'
                ORDER BY COALESCE(gp.day_order, gp.order_index), p.id
                """,
                (group_id, ProfileStatus.ACTIVE),
            ).fetchall()
        return c.execute(
            """
            SELECT p.* FROM profiles p
            JOIN group_profiles gp ON gp.profile_id = p.id
            WHERE gp.group_id=? AND gp.is_enabled=1 AND p.status=?
            ORDER BY gp.order_index, p.id
            """,
            (group_id, ProfileStatus.ACTIVE),
        ).fetchall()


def _active_groups() -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute(
            "SELECT * FROM groups WHERE is_active=1 ORDER BY id"
        ).fetchall()


def _reset_daily_counts(c: sqlite3.Connection) -> None:
    today = _local_today().isoformat()
    c.execute(
        "UPDATE profiles SET messages_sent_today=0, sent_day=?, "
        "daily_limit=NULL, daily_limit_day=NULL "
        "WHERE sent_day IS NULL OR sent_day != ?",
        (today, today),
    )


def _daily_limit_bounds() -> tuple[int, int]:
    try:
        lo = int(get_setting("daily_limit_min") or "5")
    except ValueError:
        lo = 5
    try:
        hi = int(get_setting("daily_limit_max") or "12")
    except ValueError:
        hi = 12
    if lo < 1:
        lo = 1
    if hi < 1:
        hi = 1
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def _parse_profile_created(created_at: str | None) -> date | None:
    if not created_at:
        return None
    raw = str(created_at).strip()
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _profile_age_days(profile: sqlite3.Row | dict[str, Any]) -> int:
    """Дней с created_at (0 = сегодня создан)."""
    try:
        created_raw = profile["created_at"]
    except (KeyError, IndexError, TypeError):
        created_raw = None
    created = _parse_profile_created(created_raw)
    if not created:
        return 999  # неизвестно → считаем прогретым
    return max(0, (_local_today() - created).days)


def _limit_bounds_for_profile(profile: sqlite3.Row | dict[str, Any]) -> tuple[int, int]:
    """Дневной лимит с warmup-кривой: дни 1–2 → 1–2, затем рост до полного."""
    lo, hi = _daily_limit_bounds()
    if (get_setting("warmup_enabled") or "1").strip() not in ("1", "true", "yes"):
        return lo, hi
    try:
        days = max(1, int(get_setting("warmup_days") or "7"))
    except ValueError:
        days = 7
    age = _profile_age_days(profile)
    if age >= days:
        return lo, hi
    try:
        s_lo = max(1, int(get_setting("warmup_start_min") or "1"))
    except ValueError:
        s_lo = 1
    try:
        s_hi = max(1, int(get_setting("warmup_start_max") or "2"))
    except ValueError:
        s_hi = 2
    if s_lo > s_hi:
        s_lo, s_hi = s_hi, s_lo
    # дни 1–2 (age 0–1): жёсткий старт 1–2
    if age < 2:
        return s_lo, s_hi
    # рост от старта к полному лимиту к концу warmup_days
    # age=2 .. days-1 → progress от малого к 1
    span = max(1, days - 2)
    progress = min(1.0, (age - 1) / span)
    w_lo = max(1, int(round(s_lo + (lo - s_lo) * progress)))
    w_hi = max(w_lo, int(round(s_hi + (hi - s_hi) * progress)))
    return w_lo, w_hi


def _parse_cooldown_until(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = str(raw).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _is_in_cooldown(profile: sqlite3.Row | dict[str, Any]) -> bool:
    try:
        raw = profile["cooldown_until"]
    except (KeyError, IndexError, TypeError):
        return False
    until = _parse_cooldown_until(raw)
    if not until:
        return False
    return datetime.now(timezone.utc) < until


def _set_cooldown(profile_id: int, hours: float, reason: str = "") -> None:
    if hours <= 0:
        return
    until = datetime.now(timezone.utc) + timedelta(hours=hours)
    iso = until.isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE profiles SET cooldown_until=? WHERE id=?",
            (iso, profile_id),
        )
    append_log(
        f"Пауза #{profile_id}: до {until.strftime('%Y-%m-%d %H:%M')} UTC"
        + (f" ({reason})" if reason else "")
    )


def _clear_cooldown(profile_id: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE profiles SET cooldown_until=NULL WHERE id=?",
            (profile_id,),
        )


def _ensure_daily_limit(profile_id: int, *, log: bool = True) -> int:
    """Случайный лимит на календарный день (с warmup)."""
    today = _local_today().isoformat()
    with _conn() as c:
        row = c.execute(
            "SELECT daily_limit, daily_limit_day, created_at FROM profiles WHERE id=?",
            (profile_id,),
        ).fetchone()
        if (
            row
            and row["daily_limit_day"] == today
            and row["daily_limit"] is not None
        ):
            return int(row["daily_limit"])
        lo, hi = _limit_bounds_for_profile(row) if row else _daily_limit_bounds()
        # day-skip без плана ролей (при role_plan skip задаётся в роли)
        skipped = False
        lazy = False
        if (
            _human_rhythm_enabled()
            and not _role_plan_enabled()
            and _day_skip_percent() > 0
            and random.random() * 100.0 < _day_skip_percent()
        ):
            limit = 0
            skipped = True
        else:
            # lazy day для прогретых аккаунтов
            age = _profile_age_days(row) if row else 999
            try:
                wdays = max(1, int(get_setting("warmup_days") or "7"))
            except ValueError:
                wdays = 7
            warm_on = (get_setting("warmup_enabled") or "1").strip() in (
                "1",
                "true",
                "yes",
            )
            lazy_pct = max(0.0, min(100.0, _setting_float("lazy_day_percent", 15.0)))
            if warm_on and age >= wdays and lazy_pct > 0 and random.random() * 100.0 < lazy_pct:
                factor = max(0.05, min(1.0, _setting_float("lazy_day_factor", 0.4)))
                lo = max(1, int(round(lo * factor)))
                hi = max(lo, int(round(hi * factor)))
                lazy = True
            limit = random.randint(lo, hi)
        c.execute(
            "UPDATE profiles SET daily_limit=?, daily_limit_day=? WHERE id=?",
            (limit, today, profile_id),
        )
    if log:
        if skipped:
            append_log(f"Пропуск дня #{profile_id}")
        else:
            age = _profile_age_days(row) if row else 0
            warm = ""
            try:
                days = int(get_setting("warmup_days") or "7")
            except ValueError:
                days = 7
            if (get_setting("warmup_enabled") or "1").strip() in ("1", "true", "yes") and age < days:
                warm = f" (прогрев день {age + 1}/{days})"
            if lazy:
                warm += " (ленивый день)"
            append_log(f"Дневной лимит #{profile_id} на сегодня: {limit}{warm}")
    return limit


def _can_send(profile: sqlite3.Row) -> bool:
    if _is_in_cooldown(profile):
        return False
    limit = _ensure_daily_limit(profile["id"])
    if limit <= 0:
        return False
    today = _local_today().isoformat()
    if profile["sent_day"] != today:
        return True
    return profile["messages_sent_today"] < limit


def _has_enabled_active_profiles() -> bool:
    """Есть ли enabled+active профили без учёта ролей дня."""
    with _conn() as c:
        row = c.execute(
            """
            SELECT 1 FROM profiles p
            JOIN group_profiles gp ON gp.profile_id = p.id
            JOIN groups g ON g.id = gp.group_id
            WHERE gp.is_enabled=1 AND p.status=? AND g.is_active=1
            LIMIT 1
            """,
            (ProfileStatus.ACTIVE,),
        ).fetchone()
    return row is not None


_SPINTAX_RE = re.compile(r"\{([^{}]+)\}")


def _expand_spintax(text: str) -> str:
    """Раскрыть {вариант1|вариант2} (вложенность до 10 проходов)."""
    for _ in range(10):
        def repl(m: re.Match[str]) -> str:
            parts = [p for p in m.group(1).split("|") if p != ""]
            return random.choice(parts) if parts else ""

        new = _SPINTAX_RE.sub(repl, text)
        if new == text:
            break
        text = new
    return text


def _render_message(
    text: str,
    profile: sqlite3.Row | dict[str, Any],
    group: sqlite3.Row | dict[str, Any] | None = None,
) -> str:
    """Персонализация {{phone}}/{{label}}/{{date}}/{{group}} + spintax."""
    phone = ""
    label = ""
    try:
        phone = str(profile["phone"] or "")
        label = str(profile["label"] or "")
    except (KeyError, IndexError, TypeError):
        pass
    group_name = ""
    if group is not None:
        try:
            group_name = str(group["name"] or "")
        except (KeyError, IndexError, TypeError):
            pass
    mapping = {
        "phone": phone,
        "label": label or phone,
        "date": _local_today().isoformat(),
        "group": group_name,
    }
    out = text
    for key, val in mapping.items():
        out = out.replace("{{" + key + "}}", val)
    return _expand_spintax(out)


def _human_texts_enabled() -> bool:
    return _setting_truthy("human_texts_enabled", "1")


def _normalize_message_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _text_similarity(a: str, b: str) -> float:
    na, nb = _normalize_message_text(a), _normalize_message_text(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _recent_group_texts(group_id: int, limit: int | None = None) -> list[str]:
    if limit is None:
        limit = _dedupe_window_for_group(group_id)
    with _conn() as c:
        rows = c.execute(
            """
            SELECT sent_text FROM send_log
            WHERE group_id=? AND status='sent'
              AND sent_text IS NOT NULL AND TRIM(sent_text) != ''
            ORDER BY id DESC LIMIT ?
            """,
            (group_id, limit),
        ).fetchall()
    return [str(r["sent_text"]) for r in rows]


def _is_near_duplicate(text: str, recent: list[str], max_sim: float) -> bool:
    return any(_text_similarity(text, r) >= max_sim for r in recent)


def _prepare_outgoing_text(
    text: str,
    profile: sqlite3.Row | dict[str, Any],
    group: sqlite3.Row | dict[str, Any] | None,
    group_id: int,
) -> str:
    """Spintax + анти-дубликат и разнообразие длины относительно последних в чате."""
    if not _human_texts_enabled():
        return _render_message(text, profile, group)
    dedupe = _setting_truthy("text_dedupe_enabled", "1")
    variety = _setting_truthy("text_length_variety", "1")
    max_sim = max(0.5, min(0.99, _setting_float("text_similarity_max", 0.72)))
    recent = _recent_group_texts(group_id) if dedupe or variety else []
    last_len = len(recent[0]) if recent else None
    best: str | None = None
    best_score = -1.0
    attempts = 8 if ("{" in text or "{{" in text) else 3
    for _ in range(attempts):
        cand = _render_message(text, profile, group)
        if dedupe and recent and _is_near_duplicate(cand, recent, max_sim):
            continue
        if variety and last_len is not None:
            score = float(abs(len(cand) - last_len))
        else:
            score = float(len(cand))
        if score > best_score:
            best, best_score = cand, score
    if best is not None:
        return best
    # все варианты слишком похожи — берём обычный рендер (не блокируем рассылку)
    fallback = _render_message(text, profile, group)
    if dedupe and recent and _is_near_duplicate(fallback, recent, max_sim):
        append_log(
            f"Внимание: текст похож на недавние в группе#{group_id} "
            f"(sim≥{max_sim:.2f}) — отправляем после исчерпания вариантов"
        )
    return fallback


def _human_presence_enabled() -> bool:
    return _setting_truthy("human_presence_enabled", "1")


def _presence_reaction_pool() -> list[str]:
    raw = get_setting("presence_reactions") or DEFAULTS.get(
        "presence_reactions", "👍,❤️,🔥,😂"
    )
    parts = [p.strip() for p in str(raw).replace(";", ",").split(",")]
    return [p for p in parts if p] or ["👍"]


async def _human_presence_before_send(client: Any, chat_id: int) -> None:
    """Открыть историю / иногда прочитать / иногда реакцию. Ошибки не валят send."""
    if not _human_presence_enabled():
        return
    msgs: list[Any] | None = None
    hist_ch = max(0.0, min(100.0, _setting_float("presence_history_chance", 70.0)))
    if hist_ch > 0 and random.random() * 100.0 < hist_ch:
        try:
            n = random.randint(5, 15)
            msgs = await client.fetch_history(chat_id=chat_id, backward=n)
            # «читает» + «печатает» — реалистичные 3–23 с вместо bot-паузы
            read_time = random.uniform(2.0, 8.0)
            typing_time = max(1.0, min(15.0, random.gauss(4.0, 2.0)))
            await asyncio.sleep(read_time + typing_time)
        except Exception as e:
            append_log(f"Присутствие (история): {e}")
            msgs = None
    if not msgs:
        # без истории всё равно имитируем набор текста перед send
        typing_time = max(1.0, min(12.0, random.gauss(3.5, 1.5)))
        await asyncio.sleep(typing_time)
        return
    read_ch = max(0.0, min(100.0, _setting_float("presence_read_chance", 40.0)))
    if read_ch > 0 and random.random() * 100.0 < read_ch:
        try:
            target = msgs[-1] if msgs else None
            if target is not None and getattr(target, "id", None) is not None:
                await client.read_message(int(target.id), chat_id)
        except Exception as e:
            append_log(f"Присутствие (прочтение): {e}")
    react_ch = max(0.0, min(100.0, _setting_float("presence_react_chance", 12.0)))
    if react_ch > 0 and random.random() * 100.0 < react_ch:
        try:
            candidates = [
                m
                for m in msgs
                if getattr(m, "id", None) is not None
                and (getattr(m, "text", None) or getattr(m, "attaches", None))
            ]
            if candidates:
                m = random.choice(candidates[:12])
                emoji = random.choice(_presence_reaction_pool())
                await client.add_reaction(chat_id, str(m.id), emoji)
        except Exception as e:
            append_log(f"Присутствие (реакция): {e}")


async def _maybe_idle_presence() -> None:
    """Редкий «онлайн» без отправки: открыть чат и историю."""
    if not _human_presence_enabled():
        return
    chance = max(0.0, min(100.0, _setting_float("presence_idle_chance", 5.0)))
    if chance <= 0 or random.random() * 100.0 >= chance:
        return
    if not _in_send_window():
        return
    groups = _active_groups()
    if not groups:
        return
    random.shuffle(groups)
    for group in groups[:3]:
        profiles = _active_profiles_for_group(int(group["id"]))
        if not profiles:
            continue
        profile = random.choice(profiles)
        if (
            _is_circuit_open(int(profile["id"]))
            or _is_in_human_break(int(profile["id"]))
            or _is_in_cooldown(profile)
        ):
            continue

        async def _do(c, g=group):
            cid = await resolve_chat_id(c, g)
            if not cid:
                return None
            chat_id = int(cid)
            await c.get_chat(chat_id)
            try:
                await c.fetch_history(chat_id=chat_id, backward=random.randint(3, 10))
            except Exception:
                pass
            await asyncio.sleep(random.uniform(0.3, 1.2))
            return cid

        try:
            await _with_client(
                int(profile["id"]),
                str(profile["phone"]),
                _do,
                group_id=int(group["id"]),
            )
            append_log(
                f"Простой онлайн #{profile['id']} → «{group['name']}» (без отправки)"
            )
        except Exception as e:
            append_log(f"Пропуск простоя: {e}")
        return


def _group_proxy(group_id: int, profile_id: int | None = None) -> str | None:
    """Прокси группы. Несколько URL (по строкам или через `;`) — ротация по profile_id."""
    with _conn() as c:
        row = c.execute(
            "SELECT proxy FROM groups WHERE id=?", (group_id,)
        ).fetchone()
    if not row:
        return None
    try:
        raw = (row["proxy"] or "").strip()
    except (KeyError, IndexError):
        return None
    return antiban_core.pick_proxy_from_pool(raw, profile_id)


def _dedupe_window_for_group(group_id: int) -> int:
    """Минимум из настройки; растёт с числом аккаунтов в группе (×2)."""
    configured = max(1, _setting_int("text_dedupe_window", 6))
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) n FROM group_profiles WHERE group_id=? AND is_enabled=1",
            (group_id,),
        ).fetchone()
    n = int(row["n"] if row else 0)
    return antiban_core.dedupe_window(configured, n)


def _iter_unique_active_profiles():
    seen: set[int] = set()
    for group in _active_groups():
        for p in _active_profiles_for_group(group["id"]):
            pid = int(p["id"])
            if pid in seen:
                continue
            seen.add(pid)
            yield p


def _has_active_profiles() -> bool:
    return _has_enabled_active_profiles()


def _has_sendable_profile(*, ignore_human_break: bool = False) -> bool:
    for group in _active_groups():
        for profile in _active_profiles_for_group(group["id"]):
            if _is_circuit_open(profile["id"]):
                continue
            if ignore_human_break:
                if _is_in_cooldown(profile):
                    continue
                role = _profile_day_role(profile)
                if role == "skip":
                    continue
                if not _can_send(profile):
                    continue
                if role == "quiet":
                    if _group_sends_today(int(profile["id"]), group["id"]) >= _quiet_limit():
                        continue
                return True
            if _can_send_in_group(profile, group["id"]):
                return True
    return False


def _seconds_until_any_human_break_ends() -> float:
    now = _local_now()
    waits = [
        (until - now).total_seconds()
        for until in _human_break_until.values()
        if until > now
    ]
    return max(1.0, min(waits)) if waits else 30.0


def _effective_group_limit(profile: sqlite3.Row, group_id: int) -> int:
    """Эффективный дневной лимит профиля в группе с учётом роли."""
    if _is_in_cooldown(profile):
        return 0
    role = _profile_day_role(profile)
    if role == "skip":
        return 0
    lim = _ensure_daily_limit(int(profile["id"]), log=False)
    if role == "quiet":
        return min(lim, _quiet_limit())
    return lim


def _daily_capacity_progress() -> dict[str, Any]:
    """Прогресс по дневным лимитам с учётом ролей дня (уникальные профили)."""
    today = _local_today().isoformat()
    best: dict[int, tuple[int, int]] = {}  # id -> (capacity, used)
    sendable = 0
    seen_sendable: set[int] = set()
    for group in _active_groups():
        gid = int(group["id"])
        for p in _active_profiles_for_group(gid):
            pid = int(p["id"])
            if _is_circuit_open(pid):
                continue
            cap = _effective_group_limit(p, gid)
            if cap <= 0:
                continue
            role = _profile_day_role(p)
            if role == "quiet":
                used = min(_group_sends_today(pid, gid), cap)
            else:
                used = int(p["messages_sent_today"] or 0) if p["sent_day"] == today else 0
                used = min(used, cap)
            prev = best.get(pid)
            if prev is None or cap > prev[0]:
                best[pid] = (cap, used)
            if used < cap and pid not in seen_sendable and _can_send_in_group(p, gid):
                seen_sendable.add(pid)
    capacity = sum(c for c, _u in best.values())
    sent = sum(u for _c, u in best.values())
    sendable = len(seen_sendable)
    return {
        "goal": "daily_limits",
        "sent": sent,
        "total": capacity,
        "remaining": max(0, capacity - sent),
        "sendable_profiles": sendable,
        "messages_in_pool": len(load_message_pool()),
    }


def _worker_shutdown(reason: str) -> None:
    append_log(reason)
    with _conn() as c:
        c.execute("UPDATE queue_state SET running=0 WHERE id=1")
    append_log("Воркер остановлен")
    status = "completed" if reason.startswith("Готово") else "stopped"
    _finish_campaign(status, reason)
    # уведомления в фоне
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_notify_campaign_end(status, reason))
    except RuntimeError:
        pass


def _campaign_config_snapshot() -> str:
    return json.dumps(
        {
            "delay_min_sec": get_setting("delay_min_sec"),
            "delay_max_sec": get_setting("delay_max_sec"),
            "daily_limit_min": get_setting("daily_limit_min"),
            "daily_limit_max": get_setting("daily_limit_max"),
            "jitter_percent": get_setting("jitter_percent"),
            "message_pick_mode": get_setting("message_pick_mode"),
            "campaign_goal": get_setting("campaign_goal"),
            "worker_pool_size": get_setting("worker_pool_size"),
            "human_rhythm_enabled": get_setting("human_rhythm_enabled"),
            "send_windows_weekday": get_setting("send_windows_weekday"),
            "send_windows_weekend": get_setting("send_windows_weekend"),
            "day_skip_percent": get_setting("day_skip_percent"),
            "role_plan_enabled": get_setting("role_plan_enabled"),
            "role_active_min": get_setting("role_active_min"),
            "role_active_max": get_setting("role_active_max"),
            "role_quiet_limit": get_setting("role_quiet_limit"),
            "human_pauses_enabled": get_setting("human_pauses_enabled"),
            "break_after_n": get_setting("break_after_n"),
            "warmup_start_min": get_setting("warmup_start_min"),
            "warmup_start_max": get_setting("warmup_start_max"),
            "lazy_day_percent": get_setting("lazy_day_percent"),
            "human_presence_enabled": get_setting("human_presence_enabled"),
            "human_texts_enabled": get_setting("human_texts_enabled"),
            "text_dedupe_enabled": get_setting("text_dedupe_enabled"),
            "messages_total": len(load_message_pool()),
        },
        ensure_ascii=False,
    )


def _begin_campaign(*, scheduled_for: str | None = None) -> int:
    global _current_campaign_id
    total = len(load_message_pool())
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO campaigns (started_at, status, messages_total, scheduled_for, config_json) "
            "VALUES (datetime('now'), 'running', ?, ?, ?)",
            (total, scheduled_for, _campaign_config_snapshot()),
        )
        _current_campaign_id = int(cur.lastrowid)
    append_log(f"Кампания #{_current_campaign_id} запущена ({total} сообщений)")
    return _current_campaign_id


def _finish_campaign(status: str, reason: str = "") -> None:
    global _current_campaign_id
    cid = _current_campaign_id
    if not cid:
        # найти последнюю running
        with _conn() as c:
            row = c.execute(
                "SELECT id FROM campaigns WHERE status='running' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            cid = row["id"] if row else None
    if not cid:
        return
    with _conn() as c:
        sent = c.execute(
            "SELECT COUNT(*) n FROM send_log WHERE status='sent' AND sent_at >= "
            "(SELECT started_at FROM campaigns WHERE id=?)",
            (cid,),
        ).fetchone()["n"]
        failed = c.execute(
            "SELECT COUNT(*) n FROM send_log WHERE status='failed' AND sent_at >= "
            "(SELECT started_at FROM campaigns WHERE id=?)",
            (cid,),
        ).fetchone()["n"]
        c.execute(
            "UPDATE campaigns SET finished_at=datetime('now'), status=?, "
            "messages_sent=?, messages_failed=?, reason=? WHERE id=?",
            (status, sent, failed, reason[:500], cid),
        )
    _current_campaign_id = None


def _http_post_json(url: str, payload: dict[str, Any], timeout: float = 15) -> None:
    import json

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "MAX-Sender/1.4"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        resp.read()


async def _notify_campaign_end(status: str, reason: str) -> None:
    payload = {
        "event": "campaign_finished",
        "status": status,
        "reason": reason,
        "version": APP_VERSION,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM campaigns ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row:
        payload["campaign"] = dict(row)

    webhook = get_setting("webhook_url").strip()
    if webhook:
        try:
            await asyncio.to_thread(_http_post_json, webhook, payload)
            append_log("Вебхук: уведомление отправлено")
        except Exception as e:
            append_log(f"Ошибка вебхука: {e}")

    token = get_setting("telegram_bot_token").strip()
    chat_id = get_setting("telegram_chat_id").strip()
    if token and chat_id:
        _status_ru = {
            "completed": "завершена",
            "stopped": "остановлена",
            "paused": "на паузе",
            "running": "идёт",
            "failed": "с ошибкой",
        }.get(str(status), str(status))
        text = (
            f"MAX Sender: кампания {_status_ru}\n"
            f"{reason}\n"
            f"отправлено={payload.get('campaign', {}).get('messages_sent', '?')} "
            f"ошибок={payload.get('campaign', {}).get('messages_failed', '?')}"
        )
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            await asyncio.to_thread(
                _http_post_json, url, {"chat_id": chat_id, "text": text}
            )
            append_log("Telegram: уведомление отправлено")
        except Exception as e:
            append_log(f"Telegram ошибка: {e}")


def backup_database() -> Path | None:
    """Снимок SQLite в data/backups/. Возвращает путь или None."""
    try:
        BACKUPS.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = BACKUPS / f"app-{ts}.db"
        # checkpoint WAL перед копированием
        with _conn() as c:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        shutil.copy2(DB_PATH, dest)
        files = sorted(BACKUPS.glob("app-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[BACKUP_KEEP:]:
            old.unlink(missing_ok=True)
        append_log(f"Резервная копия: {dest.name}")
        _metric_inc("backups_total")
        return dest
    except Exception as e:
        append_log(f"Ошибка резервной копии: {e}")
        return None


def _parse_iso_datetime(value: str) -> datetime:
    raw = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _reset_auth_on_startup() -> None:
    _auth_sessions.clear()
    _login_tasks.clear()
    # незавершённые кампании пометить stopped
    with _conn() as c:
        c.execute(
            "UPDATE campaigns SET status='stopped', finished_at=datetime('now'), "
            "reason='Сервер перезапущен' WHERE status='running'"
        )
        c.execute("UPDATE queue_state SET running=0 WHERE id=1")
    append_log(
        "Сервер запущен. Если вход был прерван — нажмите «Войти» снова."
    )


def _is_auth_error(err: str) -> bool:
    low = err.lower()
    return (
        "auth" in low
        or "session" in low
        or "token" in low
        or "invalidtoken" in low
        or "недействительн" in low
    )


def _touch_worker_activity() -> None:
    global _worker_last_activity
    _worker_last_activity = time.monotonic()


def _on_success(profile_id: int) -> None:
    _consecutive_errors.pop(profile_id, None)
    _circuit_opened_at.pop(profile_id, None)
    _persist_antiban_profile(profile_id)


def _on_error(profile_id: int) -> None:
    n = _consecutive_errors.get(profile_id, 0) + 1
    _consecutive_errors[profile_id] = n
    mins = max(1.0, _setting_float("circuit_break_minutes", float(CIRCUIT_BREAK_MINUTES)))
    if n >= MAX_CONSECUTIVE_ERRORS:
        _circuit_opened_at.setdefault(profile_id, time.time())
        append_log(
            f"Автопауза: профиль #{profile_id} отключён на "
            f"{int(mins)} мин после {n} ошибок подряд"
        )
    _persist_antiban_profile(profile_id)


def _is_circuit_open(profile_id: int) -> bool:
    count = _consecutive_errors.get(profile_id, 0)
    if count < MAX_CONSECUTIVE_ERRORS:
        return False
    opened = _circuit_opened_at.get(profile_id, 0.0)
    mins = max(1.0, _setting_float("circuit_break_minutes", float(CIRCUIT_BREAK_MINUTES)))
    if time.time() - opened > mins * 60:
        _on_success(profile_id)
        append_log(f"Автопауза: профиль #{profile_id} снова доступен")
        return False
    return True


def _circuit_open_count() -> int:
    return sum(1 for pid in list(_consecutive_errors) if _is_circuit_open(pid))


def _mark_profile_failed(profile_id: int, err: str, is_auth_err: bool) -> None:
    with _conn() as c:
        row = c.execute(
            "SELECT fail_count FROM profiles WHERE id=?", (profile_id,)
        ).fetchone()
        fail_count = int((row["fail_count"] if row else None) or 0) + 1
        disable_after = max(0, _setting_int("cooldown_disable_after_fails", 8))
        if is_auth_err:
            c.execute(
                "UPDATE profiles SET last_error=?, status=?, fail_count=? WHERE id=?",
                (err, ProfileStatus.NEEDS_REAUTH, fail_count, profile_id),
            )
        elif disable_after > 0 and fail_count >= disable_after:
            c.execute(
                "UPDATE profiles SET last_error=?, status=?, fail_count=? WHERE id=?",
                (err, ProfileStatus.DISABLED, fail_count, profile_id),
            )
            append_log(
                f"Профиль #{profile_id} отключён после {fail_count} ошибок подряд"
            )
            _on_error(profile_id)
            return
        else:
            c.execute(
                "UPDATE profiles SET last_error=?, fail_count=? WHERE id=?",
                (err, fail_count, profile_id),
            )
    _on_error(profile_id)
    try:
        if is_auth_err:
            hours = float(get_setting("cooldown_reauth_hours") or "24")
            _set_cooldown(profile_id, hours, "нужен повторный вход")
        else:
            base = float(get_setting("cooldown_fail_hours") or "2")
            max_h = float(get_setting("cooldown_fail_max_hours") or "48")
            hours = antiban_core.escalating_cooldown_hours(
                fail_count, base_hours=base, max_hours=max_h
            )
            _set_cooldown(profile_id, hours, f"ошибка отправки #{fail_count}")
    except ValueError:
        pass


async def _send_with_retry(
    profile: sqlite3.Row,
    group: sqlite3.Row,
    text: str,
    mi: int,
    pi: int,
    gi_next: int,
    mi_next: int,
    *,
    advance_queue: bool = True,
) -> bool:
    """Отправка с retry. True = успех, False = окончательный провал."""
    last_err = ""
    for attempt in range(MAX_RETRY):
        _touch_worker_activity()
        try:

            final_text = _prepare_outgoing_text(
                text, profile, group, int(group["id"])
            )

            async def _do(c, g=group, t=final_text):
                cid = await resolve_chat_id(c, g)
                if not cid:
                    raise RuntimeError("Не удалось определить chat_id")
                chat_id = int(cid)
                await c.get_chat(chat_id)
                await _human_presence_before_send(c, chat_id)
                await c.send_message(chat_id=chat_id, text=t)
                return cid

            await _with_client(
                profile["id"],
                profile["phone"],
                _do,
                group_id=int(group["id"]),
            )
            today = _local_today().isoformat()
            with _conn() as c:
                c.execute(
                    "UPDATE profiles SET messages_sent_today=messages_sent_today+1, "
                    "sent_day=?, last_error='', fail_count=0 WHERE id=?",
                    (today, profile["id"]),
                )
                c.execute(
                    "INSERT INTO send_log (profile_id, group_id, message_idx, status, sent_text) "
                    "VALUES (?, ?, ?, 'sent', ?)",
                    (profile["id"], group["id"], mi, final_text[:2000]),
                )
                if advance_queue:
                    c.execute(
                        "UPDATE queue_state SET profile_idx=?, message_idx=?, group_idx=? WHERE id=1",
                        (pi, mi_next, gi_next),
                    )
                else:
                    c.execute(
                        "UPDATE queue_state SET profile_idx=?, group_idx=? WHERE id=1",
                        (pi, gi_next),
                    )
            _on_success(profile["id"])
            _note_human_burst(int(profile["id"]))
            _touch_worker_activity()
            _metric_inc("messages_sent_total")
            append_log(
                f"Успех #{profile['id']} → «{group['name']}»: {final_text[:50]}…"
            )
            return True
        except Exception as e:
            last_err = str(e)
            is_auth_err = _is_auth_error(last_err)
            if is_auth_err and attempt == 0:
                append_log(
                    f"Авто-реавторизация #{profile['id']}: повтор подключения "
                    f"после ошибки сессии…"
                )
                await asyncio.sleep(2)
                _touch_worker_activity()
                continue
            if is_auth_err or attempt == MAX_RETRY - 1:
                if is_auth_err:
                    last_err = (
                        f"{last_err} — требуется повторный вход (кнопка «Войти» / «Заново»)"
                    )
                _mark_profile_failed(profile["id"], last_err, is_auth_err)
                with _conn() as c:
                    c.execute(
                        "INSERT INTO send_log (profile_id, group_id, message_idx, status, error) "
                        "VALUES (?, ?, ?, 'failed', ?)",
                        (profile["id"], group["id"], mi, last_err),
                    )
                _metric_inc("messages_failed_total")
                append_log(f"Ошибка #{profile['id']}: {last_err}")
                return False
            delay = RETRY_DELAYS[attempt]
            append_log(
                f"Попытка {attempt + 1}/{MAX_RETRY} для #{profile['id']}, "
                f"повтор через {delay}с: {last_err}"
            )
            await asyncio.sleep(delay)
            _touch_worker_activity()
    return False


def _claim_next_job() -> dict[str, Any] | str | None:
    """Атомарно взять следующее сообщение для пула.

    Returns:
      dict — задача
      \"DONE\" — очередь исчерпана (первый воркер должен завершить кампанию)
      \"STOP\" — running=0 или уже объявлен DONE
      None — временно нечего делать (нет профилей и т.п.)
    """
    global _pool_done_announced
    with _claim_lock:
        with _conn() as c:
            qs = c.execute("SELECT * FROM queue_state WHERE id=1").fetchone()
            if not qs or not qs["running"]:
                return "STOP"
            _reset_daily_counts(c)

        messages = load_message_pool()
        groups = _active_groups()
        if not messages or not groups:
            return None

        with _conn() as c:
            qs = c.execute("SELECT * FROM queue_state WHERE id=1").fetchone()
            if not qs or not qs["running"]:
                return "STOP"
            pi, mi, gi = qs["profile_idx"], qs["message_idx"], qs["group_idx"]

            if _campaign_goal() == "message_pool":
                if _message_pick_mode() == "random_norepeat":
                    bag = _ensure_message_bag(c, len(messages))
                    if not bag:
                        if not _pool_done_announced:
                            _pool_done_announced = True
                            return "DONE"
                        return "STOP"
                elif mi >= len(messages):
                    if not _pool_done_announced:
                        _pool_done_announced = True
                        return "DONE"
                    return "STOP"

            group = groups[gi % len(groups)]
            profiles = _active_profiles_for_group(group["id"])
            if not profiles:
                if not _has_active_profiles():
                    if not _pool_done_announced:
                        _pool_done_announced = True
                        return "NO_PROFILES"
                    return "STOP"
                c.execute(
                    "UPDATE queue_state SET group_idx=? WHERE id=1",
                    (next_index(gi, len(groups)),),
                )
                return None

            profile = None
            attempts = 0
            while attempts < len(profiles):
                cand = profiles[pi % len(profiles)]
                pi = next_index(pi, len(profiles))
                attempts += 1
                if _is_circuit_open(cand["id"]):
                    continue
                if not _can_send_in_group(cand, group["id"]):
                    continue
                profile = cand
                break

            if profile is None:
                c.execute(
                    "UPDATE queue_state SET profile_idx=?, group_idx=? WHERE id=1",
                    (pi, next_index(gi, len(groups))),
                )
                return None

            picked = _pick_next_message(c, messages, mi)
            if picked is None:
                if not _pool_done_announced:
                    _pool_done_announced = True
                    return "DONE"
                return "STOP"

            text, pool_idx, progress_next, bag_mode = picked
            gi_next = next_index(gi, len(groups))
            if bag_mode:
                c.execute(
                    "UPDATE queue_state SET profile_idx=?, group_idx=? WHERE id=1",
                    (pi, gi_next),
                )
            else:
                c.execute(
                    "UPDATE queue_state SET message_idx=?, profile_idx=?, group_idx=? WHERE id=1",
                    (progress_next, pi, gi_next),
                )
            return {
                "profile": profile,
                "group": group,
                "text": text,
                "mi": pool_idx,
                "pi": pi,
                "gi_next": gi_next,
                "mi_next": progress_next,
            }


async def _pool_worker_loop(worker_id: int) -> None:
    append_log(f"Воркер пула #{worker_id} стартовал")
    # Расфазировка: не ускоряем паузы, а разводим воркеры по времени
    n = _pool_size()
    if n > 1 and worker_id > 1:
        base = float(_setting_int("delay_min_sec", 60))
        phase = random.uniform(0.0, max(5.0, base * 0.6))
        stagger = phase * ((worker_id - 1) / max(1, n - 1))
        end_at = time.monotonic() + stagger
        while time.monotonic() < end_at:
            _touch_worker_activity()
            await asyncio.sleep(min(5.0, end_at - time.monotonic()))
    _touch_worker_activity()
    while True:
        _touch_worker_activity()
        if await _wait_if_outside_send_window():
            continue
        await _maybe_idle_presence()
        job = _claim_next_job()
        if job == "STOP":
            append_log(f"Воркер пула #{worker_id} остановлен")
            return
        if job == "DONE":
            if _campaign_goal() == "daily_limits":
                _worker_shutdown(
                    "Готово: дневные лимиты всех аккаунтов исчерпаны"
                )
            else:
                _worker_shutdown("Готово: все сообщения отправлены (pool)")
            return
        if job == "NO_PROFILES":
            _worker_shutdown("Нет активных профилей ни в одной группе")
            return
        if job is None:
            if not _has_sendable_profile():
                if _has_sendable_profile(ignore_human_break=True):
                    wait = min(60.0, _seconds_until_any_human_break_ends())
                    end_at = time.monotonic() + wait
                    while time.monotonic() < end_at:
                        _touch_worker_activity()
                        await asyncio.sleep(min(15.0, end_at - time.monotonic()))
                    continue
                _worker_shutdown(
                    "Готово: дневные лимиты всех аккаунтов исчерпаны"
                    if _campaign_goal() == "daily_limits"
                    else "Некому отправлять: нет активных профилей или дневной лимит исчерпан"
                )
                return
            await asyncio.sleep(2)
            continue

        sent = await _send_with_retry(
            job["profile"],
            job["group"],
            job["text"],
            job["mi"],
            job["pi"],
            job["gi_next"],
            job["mi_next"],
            advance_queue=False,
        )
        if not sent:
            _return_to_message_bag(job["mi"])
            await asyncio.sleep(3)
            _touch_worker_activity()
            continue
        await _sleep_send_delay(pool_scale=True)


async def _worker_loop() -> None:
    append_log("Воркер запущен")
    _touch_worker_activity()
    while True:
        _touch_worker_activity()
        if await _wait_if_outside_send_window():
            continue
        await _maybe_idle_presence()
        with _conn() as c:
            qs = c.execute("SELECT * FROM queue_state WHERE id=1").fetchone()
            if not qs or not qs["running"]:
                append_log("Воркер остановлен")
                return
            _reset_daily_counts(c)

        messages = load_message_pool()
        groups = _active_groups()
        if not messages:
            append_log("Нет сообщений — загрузите файл сообщений (.txt)")
            await asyncio.sleep(5)
            continue
        if not groups:
            append_log("Нет активных групп")
            await asyncio.sleep(5)
            continue

        with _conn() as c:
            qs = c.execute("SELECT * FROM queue_state WHERE id=1").fetchone()
            pi, mi, gi = qs["profile_idx"], qs["message_idx"], qs["group_idx"]
            if _campaign_goal() == "message_pool":
                if _message_pick_mode() == "random_norepeat":
                    bag = _ensure_message_bag(c, len(messages))
                    if not bag:
                        _worker_shutdown(
                            f"Готово: все {len(messages)} сообщений отправлены"
                        )
                        return
                elif mi >= len(messages):
                    _worker_shutdown(
                        f"Готово: все {len(messages)} сообщений отправлены"
                    )
                    return

        group = groups[gi % len(groups)]
        profiles = _active_profiles_for_group(group["id"])
        if not profiles:
            if not _has_active_profiles():
                _worker_shutdown("Нет активных профилей ни в одной группе")
                return
            append_log(
                f"Группа «{group['name']}»: сегодня некого слать "
                f"(роли/skip), следующая"
            )
            with _conn() as c:
                c.execute(
                    "UPDATE queue_state SET group_idx=? WHERE id=1",
                    (next_index(gi, len(groups)),),
                )
            await asyncio.sleep(2)
            continue

        # ponytail: linear scan for next sendable profile (O(n) per step; fine for 1000)
        sent = False
        attempts = 0
        while attempts < len(profiles) and not sent:
            profile = profiles[pi % len(profiles)]
            pi = next_index(pi, len(profiles))
            attempts += 1
            if _is_circuit_open(profile["id"]):
                continue
            if not _can_send_in_group(profile, group["id"]):
                continue

            with _conn() as c:
                picked = _pick_next_message(c, messages, mi)
            if picked is None:
                _worker_shutdown(
                    f"Готово: все {len(messages)} сообщений отправлены"
                )
                return
            text, pool_idx, progress_next, bag_mode = picked
            gi_next = next_index(gi, len(groups))
            sent = await _send_with_retry(
                profile,
                group,
                text,
                pool_idx,
                pi,
                gi_next,
                progress_next,
                advance_queue=not bag_mode,
            )
            if not sent and bag_mode:
                _return_to_message_bag(pool_idx)
            mi = progress_next

        if sent:
            await _sleep_send_delay(pool_scale=False)
        else:
            if not _has_sendable_profile():
                if _has_sendable_profile(ignore_human_break=True):
                    wait = min(60.0, _seconds_until_any_human_break_ends())
                    end_at = time.monotonic() + wait
                    while time.monotonic() < end_at:
                        _touch_worker_activity()
                        await asyncio.sleep(min(15.0, end_at - time.monotonic()))
                    continue
                _worker_shutdown(
                    "Готово: дневные лимиты всех аккаунтов исчерпаны"
                    if _campaign_goal() == "daily_limits"
                    else "Некому отправлять: нет активных профилей или дневной лимит исчерпан"
                )
                return
            # в этой группе некого — переходим к следующей
            with _conn() as c:
                c.execute(
                    "UPDATE queue_state SET profile_idx=?, group_idx=? WHERE id=1",
                    (pi, next_index(gi, len(groups))),
                )
            open_ids = [p["id"] for p in profiles if _is_circuit_open(p["id"])]
            if open_ids and len(open_ids) >= len(profiles):
                append_log(
                    "Все профили группы в автопаузе — следующая группа"
                )
            await asyncio.sleep(1)
            _touch_worker_activity()


async def _pool_supervisor() -> None:
    global _pool_tasks, _pool_done_announced
    n = _pool_size()
    _pool_done_announced = False
    append_log(f"Пул воркеров: {n} параллельных")
    _pool_tasks = [asyncio.create_task(_pool_worker_loop(i + 1)) for i in range(n)]
    try:
        await asyncio.gather(*_pool_tasks)
    except asyncio.CancelledError:
        for t in _pool_tasks:
            t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*_pool_tasks, return_exceptions=True)
        raise
    finally:
        _pool_tasks = []


async def _watchdog_loop() -> None:
    while True:
        await asyncio.sleep(60)
        if _shutting_down:
            return
        if _worker_task and not _worker_task.done():
            idle = time.monotonic() - _worker_last_activity
            if idle > WORKER_TIMEOUT:
                append_log(
                    f"Сторож: воркер завис ({idle:.0f}с без активности) — перезапуск"
                )
                await _stop_worker(finish_status="stopped", reason="Перезапуск сторожем")
                await _start_worker(record_campaign=False)


async def _scheduler_loop() -> None:
    while True:
        await asyncio.sleep(15)
        if _shutting_down:
            return
        try:
            with _conn() as c:
                row = c.execute(
                    "SELECT * FROM campaign_schedule WHERE id=1"
                ).fetchone()
            if not row or not row["enabled"] or not row["start_at"]:
                continue
            start_at = _parse_iso_datetime(row["start_at"])
            now = datetime.now(timezone.utc)
            if now < start_at:
                continue
            if _worker_task and not _worker_task.done():
                continue
            # срабатывание
            with _conn() as c:
                c.execute(
                    "UPDATE campaign_schedule SET enabled=0 WHERE id=1"
                )
            append_log(f"Расписание: старт кампании (запланировано на {row['start_at']})")
            try:
                _require_vault_unlocked()
            except HTTPException as e:
                append_log(f"Расписание: пропуск — {e.detail}")
                continue
            if not load_message_pool() or not _has_sendable_profile():
                append_log("Расписание: нет сообщений или профилей — пропуск")
                continue
            await _start_worker(scheduled_for=row["start_at"])
        except Exception as e:
            append_log(f"Ошибка планировщика: {e}")


async def _backup_loop() -> None:
    last_backup = 0.0
    while True:
        await asyncio.sleep(60)
        if _shutting_down:
            return
        try:
            hours = float(get_setting("backup_interval_hours") or "24")
        except ValueError:
            hours = 24.0
        if hours <= 0:
            continue
        now = time.monotonic()
        if last_backup == 0.0:
            backup_database()
            last_backup = now
            continue
        if now - last_backup >= hours * 3600:
            backup_database()
            last_backup = now


async def _start_worker(
    *,
    record_campaign: bool = True,
    scheduled_for: str | None = None,
) -> None:
    """Запуск воркера / пула без сброса индексов прогресса."""
    global _worker_task, _pool_done_announced
    async with _worker_lock:
        if _worker_task and not _worker_task.done():
            return
        _touch_worker_activity()
        _pool_done_announced = False
        with _conn() as c:
            c.execute("UPDATE queue_state SET running=1 WHERE id=1")
            # колода на старте, если ещё не собрана
            msgs = load_message_pool()
            if _message_pick_mode() == "random_norepeat" and msgs:
                qs = c.execute("SELECT message_idx FROM queue_state WHERE id=1").fetchone()
                if int(qs["message_idx"] if qs else 0) == 0 and not _get_message_bag(c):
                    bag = list(range(len(msgs)))
                    random.shuffle(bag)
                    _set_message_bag(c, bag)
        if record_campaign:
            _begin_campaign(scheduled_for=scheduled_for)
            _metric_inc("campaigns_started_total")
        n = _pool_size()
        if n > 1:
            _worker_task = asyncio.create_task(_pool_supervisor())
        else:
            _worker_task = asyncio.create_task(_worker_loop())


def _reset_queue_progress() -> None:
    n = len(load_message_pool())
    with _conn() as c:
        c.execute(
            "UPDATE queue_state SET profile_idx=0, message_idx=0, group_idx=0 WHERE id=1"
        )
    _rebuild_message_bag(n)


async def _stop_worker(
    *,
    finish_status: str | None = "stopped",
    reason: str = "Остановлено пользователем",
) -> None:
    global _worker_task, _pool_tasks
    was_running = bool(_worker_task and not _worker_task.done())
    with _conn() as c:
        c.execute("UPDATE queue_state SET running=0 WHERE id=1")
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
    for t in list(_pool_tasks):
        t.cancel()
    _pool_tasks = []
    if was_running and finish_status:
        with _conn() as c:
            still = c.execute(
                "SELECT 1 FROM campaigns WHERE status='running' LIMIT 1"
            ).fetchone()
        if still:
            _finish_campaign(finish_status, reason)
            _metric_inc("campaigns_finished_total")
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_notify_campaign_end(finish_status, reason))
            except RuntimeError:
                pass


# --- API models --------------------------------------------------------------


class ProfileIn(BaseModel):
    phone: str
    label: str = ""
    proxy: str = ""


class ProfilePatchIn(BaseModel):
    label: str | None = None
    proxy: str | None = None


class CodeIn(BaseModel):
    code: str


class GroupIn(BaseModel):
    name: str
    max_chat_id: str = ""
    invite_link: str = ""
    proxy: str = ""


class GroupPatchIn(BaseModel):
    name: str | None = None
    max_chat_id: str | None = None
    invite_link: str | None = None
    proxy: str | None = None


class SettingsIn(BaseModel):
    delay_min_sec: int | None = None
    delay_max_sec: int | None = None
    max_msgs_per_profile_day: int | None = None
    daily_limit_min: int | None = None
    daily_limit_max: int | None = None
    jitter_percent: int | None = None
    message_pick_mode: str | None = None
    campaign_goal: str | None = None
    warmup_enabled: int | None = None
    warmup_days: int | None = None
    cooldown_reauth_hours: float | None = None
    cooldown_fail_hours: float | None = None
    password_max_attempts: int | None = None
    api_pin: str | None = None
    webhook_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    backup_interval_hours: float | None = None
    worker_pool_size: int | None = None
    human_rhythm_enabled: int | None = None
    send_windows_weekday: str | None = None
    send_windows_weekend: str | None = None
    day_skip_percent: float | None = None
    role_plan_enabled: int | None = None
    role_active_min: int | None = None
    role_active_max: int | None = None
    role_quiet_limit: int | None = None
    human_pauses_enabled: int | None = None
    short_pause_chance: float | None = None
    short_pause_min_sec: int | None = None
    short_pause_max_sec: int | None = None
    long_pause_chance: float | None = None
    long_pause_min_sec: int | None = None
    long_pause_max_sec: int | None = None
    break_after_n: int | None = None
    break_min_sec: int | None = None
    break_max_sec: int | None = None
    jitter_morning_percent: int | None = None
    jitter_evening_percent: int | None = None
    warmup_start_min: int | None = None
    warmup_start_max: int | None = None
    lazy_day_percent: float | None = None
    lazy_day_factor: float | None = None
    human_presence_enabled: int | None = None
    presence_history_chance: float | None = None
    presence_read_chance: float | None = None
    presence_react_chance: float | None = None
    presence_reactions: str | None = None
    presence_idle_chance: float | None = None
    human_texts_enabled: int | None = None
    text_dedupe_enabled: int | None = None
    text_similarity_max: float | None = None
    text_dedupe_window: int | None = None
    text_length_variety: int | None = None
    timezone_offset_hours: float | None = None
    circuit_break_minutes: float | None = None
    cooldown_fail_max_hours: float | None = None
    cooldown_disable_after_fails: int | None = None

    @model_validator(mode="after")
    def check_delays(self) -> SettingsIn:
        lo = self.delay_min_sec
        hi = self.delay_max_sec
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("Мин. пауза не может быть больше макс. паузы")
        if self.jitter_percent is not None and not (0 <= self.jitter_percent <= 100):
            raise ValueError("Разброс (%) должен быть от 0 до 100")
        if self.max_msgs_per_profile_day is not None and self.max_msgs_per_profile_day < 1:
            raise ValueError("Лимит сообщений в день должен быть ≥ 1")
        dlo, dhi = self.daily_limit_min, self.daily_limit_max
        if dlo is not None and dlo < 1:
            raise ValueError("Лимит/день мин должен быть ≥ 1")
        if dhi is not None and dhi < 1:
            raise ValueError("Лимит/день макс должен быть ≥ 1")
        if dlo is not None and dhi is not None and dlo > dhi:
            raise ValueError("Лимит/день мин не может быть больше макс")
        if self.message_pick_mode is not None and self.message_pick_mode not in (
            "random_norepeat",
            "round_robin",
        ):
            raise ValueError("Режим сообщений: случайно без повтора или по кругу")
        if self.campaign_goal is not None and self.campaign_goal not in (
            "daily_limits",
            "message_pool",
        ):
            raise ValueError("Цель кампании: дневные лимиты или пул сообщений")
        if self.warmup_days is not None and self.warmup_days < 1:
            raise ValueError("Дней прогрева должно быть ≥ 1")
        if self.cooldown_reauth_hours is not None and self.cooldown_reauth_hours < 0:
            raise ValueError("Пауза после повторного входа (ч) должна быть ≥ 0")
        if self.cooldown_fail_hours is not None and self.cooldown_fail_hours < 0:
            raise ValueError("Пауза после ошибки (ч) должна быть ≥ 0")
        if self.password_max_attempts is not None and self.password_max_attempts < 1:
            raise ValueError("Макс. попыток пароля должно быть ≥ 1")
        if self.backup_interval_hours is not None and self.backup_interval_hours < 0:
            raise ValueError("Интервал резервной копии (ч) должен быть ≥ 0")
        if self.worker_pool_size is not None and not (1 <= self.worker_pool_size <= 32):
            raise ValueError("Пул воркеров должен быть от 1 до 32")
        if self.day_skip_percent is not None and not (0 <= self.day_skip_percent <= 100):
            raise ValueError("Пропуск дня (%) должен быть от 0 до 100")
        if self.role_active_min is not None and self.role_active_min < 0:
            raise ValueError("Активных мин должно быть ≥ 0")
        if self.role_active_max is not None and self.role_active_max < 0:
            raise ValueError("Активных макс должно быть ≥ 0")
        if (
            self.role_active_min is not None
            and self.role_active_max is not None
            and self.role_active_min > self.role_active_max
        ):
            raise ValueError("Активных мин не может быть больше макс")
        if self.role_quiet_limit is not None and self.role_quiet_limit < 0:
            raise ValueError("Лимит тихих должен быть ≥ 0")
        for pct_name, pct_val in (
            ("short_pause_chance", self.short_pause_chance),
            ("long_pause_chance", self.long_pause_chance),
            ("lazy_day_percent", self.lazy_day_percent),
            ("jitter_morning_percent", self.jitter_morning_percent),
            ("jitter_evening_percent", self.jitter_evening_percent),
            ("presence_history_chance", self.presence_history_chance),
            ("presence_read_chance", self.presence_read_chance),
            ("presence_react_chance", self.presence_react_chance),
            ("presence_idle_chance", self.presence_idle_chance),
        ):
            if pct_val is not None and not (0 <= pct_val <= 100):
                raise ValueError(f"Параметр «{pct_name}» должен быть от 0 до 100")
        if self.text_similarity_max is not None and not (
            0.5 <= self.text_similarity_max <= 0.99
        ):
            raise ValueError("Сходство текстов должно быть от 0.5 до 0.99")
        if self.text_dedupe_window is not None and self.text_dedupe_window < 1:
            raise ValueError("Окно антидублей должно быть ≥ 1")
        _range_labels = {
            "short_pause": "Короткая пауза",
            "long_pause": "Длинная пауза",
            "break": "Перерыв",
            "warmup_start": "Прогрев старт",
        }
        for a, b, name in (
            (self.short_pause_min_sec, self.short_pause_max_sec, "short_pause"),
            (self.long_pause_min_sec, self.long_pause_max_sec, "long_pause"),
            (self.break_min_sec, self.break_max_sec, "break"),
            (self.warmup_start_min, self.warmup_start_max, "warmup_start"),
        ):
            label = _range_labels.get(name, name)
            if a is not None and a < 0:
                raise ValueError(f"{label}: мин должно быть ≥ 0")
            if b is not None and b < 0:
                raise ValueError(f"{label}: макс должно быть ≥ 0")
            if a is not None and b is not None and a > b:
                raise ValueError(f"{label}: мин не может быть больше макс")
        if self.break_after_n is not None and self.break_after_n < 0:
            raise ValueError("Перерыв после N должен быть ≥ 0")
        if self.lazy_day_factor is not None and not (0.05 <= self.lazy_day_factor <= 1.0):
            raise ValueError("Коэффициент ленивого дня должен быть от 0.05 до 1.0")
        for field, raw, field_ru in (
            ("send_windows_weekday", self.send_windows_weekday, "Окна будни"),
            ("send_windows_weekend", self.send_windows_weekend, "Окна выходные"),
        ):
            if raw is None:
                continue
            s = str(raw).strip()
            if not s:
                continue
            if not _parse_send_windows(s):
                raise ValueError(
                    f"{field_ru}: ожидается формат вроде 9-13,16-21 или 09:00-13:00"
                )
        if self.timezone_offset_hours is not None and not (
            -12.0 <= self.timezone_offset_hours <= 14.0
        ):
            raise ValueError("Часовой пояс UTC+ должен быть от -12 до 14")
        if self.circuit_break_minutes is not None and self.circuit_break_minutes < 1:
            raise ValueError("Автопауза (мин) должна быть ≥ 1")
        if self.cooldown_fail_max_hours is not None and self.cooldown_fail_max_hours < 0:
            raise ValueError("Макс. пауза после ошибки (ч) должна быть ≥ 0")
        if (
            self.cooldown_disable_after_fails is not None
            and self.cooldown_disable_after_fails < 0
        ):
            raise ValueError("Отключение после N ошибок должно быть ≥ 0")
        return self


class VaultPasswordIn(BaseModel):
    password: str


class BulkProfilesIn(BaseModel):
    profiles: list[ProfileIn]


class ScheduleIn(BaseModel):
    start_at: str  # ISO-8601


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api"):
            return await call_next(request)
        if request.url.path in ("/api/health", "/api/vault/status", "/metrics"):
            return await call_next(request)
        ip = request.client.host if request.client else "127.0.0.1"
        now = time.monotonic()
        window = _rate_counters[ip]
        _rate_counters[ip] = [t for t in window if now - t < RATE_WINDOW]
        if len(_rate_counters[ip]) >= RATE_LIMIT:
            return JSONResponse(
                status_code=429, content={"detail": "Слишком много запросов"}
            )
        _rate_counters[ip].append(now)
        return await call_next(request)


class ApiPinMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _is_server_mode():
            return await call_next(request)
        path = request.url.path
        if (
            path == "/"
            or path.startswith("/static")
            or path == "/api/health"
            or path == "/api/vault/status"
            or path == "/metrics"
            or path.startswith("/ws/")
        ):
            return await call_next(request)
        stored = get_setting("api_pin").strip()
        if not stored:
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if not token:
            token = request.headers.get("X-API-Key") or ""
        if not _verify_pin(token, stored):
            return JSONResponse(status_code=401, content={"detail": "Неверный PIN API"})
        # миграция plaintext PIN → scrypt
        if token and stored and not stored.startswith(PIN_HASH_PREFIX):
            set_setting("api_pin", _hash_pin(token))
        return await call_next(request)


# --- FastAPI -----------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _watchdog_task, _scheduler_task, _backup_task, _shutting_down
    init_db()
    _load_log_from_db()
    _load_antiban_state()
    _try_legacy_unlock()
    _reset_auth_on_startup()
    if not _is_test_mode():
        _watchdog_task = asyncio.create_task(_watchdog_loop())
        _scheduler_task = asyncio.create_task(_scheduler_loop())
        _backup_task = asyncio.create_task(_backup_loop())
    try:
        yield
    finally:
        _shutting_down = True
        if not _is_test_mode():
            for task in (_watchdog_task, _scheduler_task, _backup_task):
                if task:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            _watchdog_task = _scheduler_task = _backup_task = None
        await _stop_worker(finish_status="stopped", reason="Остановка сервера")
        _encrypt_all_sessions()


def _encrypt_all_sessions() -> None:
    for profile_id in list(_auth_sessions.keys()):
        try:
            _encrypt_session(profile_id)
        except Exception:
            pass
    try:
        if SESSIONS.exists():
            for d in SESSIONS.iterdir():
                if d.is_dir() and (d / "session.db").exists():
                    try:
                        _encrypt_session(int(d.name))
                    except (ValueError, OSError):
                        pass
    except OSError:
        pass


app = FastAPI(title="MAX Sender", lifespan=lifespan)
app.add_middleware(ApiPinMiddleware)
app.add_middleware(RateLimitMiddleware)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/auth.html")
async def auth_page():
    return FileResponse(STATIC / "auth.html")


@app.get("/admin.html")
async def admin_page():
    return FileResponse(STATIC / "admin.html")


@app.get("/api/health")
async def health():
    try:
        if _is_server_mode():
            import server.app.db_pg as db_pg

            db_pg._get_conn().execute("SELECT 1")
            db_ok = True
        else:
            with _conn() as c:
                c.execute("SELECT 1").fetchone()
            db_ok = True
    except Exception:
        db_ok = False
    vs = vault_status()
    return {
        "ok": db_ok and (vs["unlocked"] or vs["needs_setup"] or vs["legacy"]),
        "db_ok": db_ok,
        "server_mode": _is_server_mode(),
        "worker_running": bool(_worker_task and not _worker_task.done()),
        "worker_pool_size": _pool_size(),
        "db_backend": DB_BACKEND,
        "redis_configured": bool(REDIS_URL),
        "celery_enabled": USE_CELERY,
        "vault": vs,
        "circuit_open": _circuit_open_count(),
        "version": APP_VERSION,
    }


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus text exposition format."""
    lines = [
        "# HELP max_sender_info Build info",
        "# TYPE max_sender_info gauge",
        f'max_sender_info{{version="{APP_VERSION}",db="{DB_BACKEND}"}} 1',
        "# HELP max_sender_messages_sent_total Sent messages",
        "# TYPE max_sender_messages_sent_total counter",
        f"max_sender_messages_sent_total {_metrics.get('messages_sent_total', 0):.0f}",
        "# HELP max_sender_messages_failed_total Failed messages",
        "# TYPE max_sender_messages_failed_total counter",
        f"max_sender_messages_failed_total {_metrics.get('messages_failed_total', 0):.0f}",
        "# HELP max_sender_campaigns_started_total Campaigns started",
        "# TYPE max_sender_campaigns_started_total counter",
        f"max_sender_campaigns_started_total {_metrics.get('campaigns_started_total', 0):.0f}",
        "# HELP max_sender_campaigns_finished_total Campaigns finished",
        "# TYPE max_sender_campaigns_finished_total counter",
        f"max_sender_campaigns_finished_total {_metrics.get('campaigns_finished_total', 0):.0f}",
        "# HELP max_sender_worker_running Worker running flag",
        "# TYPE max_sender_worker_running gauge",
        f"max_sender_worker_running {1 if (_worker_task and not _worker_task.done()) else 0}",
        "# HELP max_sender_worker_pool_size Configured pool size",
        "# TYPE max_sender_worker_pool_size gauge",
        f"max_sender_worker_pool_size {_pool_size()}",
        "# HELP max_sender_circuit_open Profiles in circuit breaker",
        "# TYPE max_sender_circuit_open gauge",
        f"max_sender_circuit_open {_circuit_open_count()}",
        "# HELP max_sender_backups_total DB backups created",
        "# TYPE max_sender_backups_total counter",
        f"max_sender_backups_total {_metrics.get('backups_total', 0):.0f}",
    ]
    body = "\n".join(lines) + "\n"
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/api/vault/status")
async def api_vault_status():
    return vault_status()


@app.post("/api/vault/setup")
async def api_vault_setup(body: VaultPasswordIn):
    try:
        return setup_vault(body.password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/vault/unlock")
async def api_vault_unlock(body: VaultPasswordIn):
    try:
        unlock_vault(body.password)
    except ValueError as e:
        raise HTTPException(401, str(e)) from e
    return {"ok": True, **vault_status()}


@app.post("/api/vault/lock")
async def api_vault_lock():
    if vault_status()["legacy"]:
        raise HTTPException(
            400,
            "Старый ключ нельзя заблокировать — сначала защитите хранилище паролем",
        )
    if not vault_status()["protected"]:
        raise HTTPException(400, "Хранилище ещё не защищено")
    lock_vault()
    return {"ok": True, **vault_status()}


@app.get("/api/status")
async def status():
    return _build_status_payload()


def _build_status_payload() -> dict[str, Any]:
    with _conn() as c:
        qs = c.execute("SELECT * FROM queue_state WHERE id=1").fetchone()
        counts = c.execute(
            "SELECT status, COUNT(*) n FROM profiles GROUP BY status"
        ).fetchall()
    messages_total = len(load_message_pool())
    message_idx = qs["message_idx"] if qs else 0
    if _campaign_goal() == "daily_limits":
        progress = _daily_capacity_progress()
    else:
        progress = {
            "goal": "message_pool",
            "sent": min(message_idx, messages_total),
            "total": messages_total,
            "remaining": max(0, messages_total - message_idx),
            "messages_in_pool": messages_total,
        }
    return {
        "running": bool(qs and qs["running"]),
        "queue": dict(qs) if qs else {},
        "profiles": {r["status"]: r["n"] for r in counts},
        "messages_count": messages_total,
        "campaign_progress": progress,
        "campaign_goal": _campaign_goal(),
        "message_pick_mode": _message_pick_mode(),
        "vault": vault_status(),
        "circuit_open": _circuit_open_count(),
        "worker_pool_size": _pool_size(),
        "db_backend": DB_BACKEND,
        "log": _log[-80:],
        "version": APP_VERSION,
    }


def _ws_pin_ok(pin: str) -> bool:
    stored = get_setting("api_pin").strip()
    if not stored:
        return True
    return _verify_pin(pin or "", stored)


@app.websocket("/ws/status")
async def ws_status(ws: WebSocket):
    """Пуш статуса ~1/с. PIN: ?pin=… (браузерный WS не шлёт Authorization)."""
    pin = (ws.query_params.get("pin") or "").strip()
    if not _ws_pin_ok(pin):
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        while not _shutting_down:
            await ws.send_json(_build_status_payload())
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass
    except Exception:
        with contextlib.suppress(Exception):
            await ws.close()


def _normalize_phone(phone: str) -> str:
    phone = phone.strip()
    if not phone.startswith("+"):
        phone = "+" + phone.lstrip("+")
    return phone


def _ensure_auth_session(profile_id: int) -> dict[str, Any]:
    if profile_id not in _auth_sessions:
        _auth_sessions[profile_id] = {
            "sms_q": asyncio.Queue(),
            "pwd_q": asyncio.Queue(),
            "step": "idle",
            "hint": "",
        }
    return _auth_sessions[profile_id]


def _set_auth_step(profile_id: int, step: str, hint: str = "") -> None:
    sess = _ensure_auth_session(profile_id)
    sess["step"] = step
    sess["hint"] = hint


def _drain_queue(q: asyncio.Queue) -> None:
    while not q.empty():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            break


def _profile_auth_view(p: sqlite3.Row | dict) -> dict:
    d = dict(p)
    sess = _auth_sessions.get(d["id"], {})
    d["auth_step"] = sess.get("step", "idle")
    d["auth_hint"] = sess.get("hint", "")
    d["in_cooldown"] = _is_in_cooldown(d)
    d["circuit_open"] = _is_circuit_open(int(d["id"]))
    try:
        wdays = max(1, int(get_setting("warmup_days") or "7"))
    except ValueError:
        wdays = 7
    age = _profile_age_days(d)
    d["warmup_day"] = min(age + 1, wdays)
    d["warmup_active"] = (
        (get_setting("warmup_enabled") or "1").strip() in ("1", "true", "yes")
        and age < wdays
    )
    return d


def _profiles_for_group(c: sqlite3.Connection, group_id: int) -> list[sqlite3.Row]:
    return c.execute(
        """
        SELECT p.*, gp.order_index FROM profiles p
        JOIN group_profiles gp ON gp.profile_id = p.id
        WHERE gp.group_id=? AND gp.is_enabled=1
        ORDER BY gp.order_index, p.id
        """,
        (group_id,),
    ).fetchall()


def _delete_profile_if_orphan(profile_id: int) -> None:
    with _conn() as c:
        linked = c.execute(
            "SELECT 1 FROM group_profiles WHERE profile_id=?", (profile_id,)
        ).fetchone()
        if linked:
            return
        c.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
    d = SESSIONS / str(profile_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    _auth_sessions.pop(profile_id, None)


@app.get("/api/profiles")
async def list_profiles(offset: int = 0, limit: int = 50, q: str = ""):
    """Только профили, привязанные хотя бы к одной группе."""
    base = """
        FROM profiles p
        WHERE EXISTS (SELECT 1 FROM group_profiles gp WHERE gp.profile_id = p.id)
    """
    with _conn() as c:
        if q:
            rows = c.execute(
                f"SELECT p.* {base} AND (p.phone LIKE ? OR p.label LIKE ?) "
                "ORDER BY p.id LIMIT ? OFFSET ?",
                (f"%{q}%", f"%{q}%", limit, offset),
            ).fetchall()
            total = c.execute(
                f"SELECT COUNT(*) n {base} AND (p.phone LIKE ? OR p.label LIKE ?)",
                (f"%{q}%", f"%{q}%"),
            ).fetchone()["n"]
        else:
            rows = c.execute(
                f"SELECT p.* {base} ORDER BY p.id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            total = c.execute(f"SELECT COUNT(*) n {base}").fetchone()["n"]
    return {"items": [dict(r) for r in rows], "total": total}


@app.get("/api/profiles/{profile_id}")
async def get_profile(profile_id: int):
    with _conn() as c:
        p = c.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
    if not p:
        raise HTTPException(404, "Профиль не найден")
    return _profile_auth_view(p)


@app.patch("/api/profiles/{profile_id}")
async def patch_profile(profile_id: int, body: ProfilePatchIn):
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "Нечего обновлять")
    with _conn() as c:
        p = c.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
        if not p:
            raise HTTPException(404, "Профиль не найден")
        if "label" in data:
            c.execute(
                "UPDATE profiles SET label=? WHERE id=?",
                (str(data["label"] or "").strip(), profile_id),
            )
        if "proxy" in data:
            proxy = str(data["proxy"] or "").strip()
            c.execute(
                "UPDATE profiles SET proxy=? WHERE id=?",
                (proxy, profile_id),
            )
            append_log(
                f"Прокси #{profile_id}: {'задан' if proxy else 'очищен'}"
            )
        p2 = c.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
    return _profile_auth_view(p2)


@app.post("/api/profiles/{profile_id}/login/reset")
async def reset_login(profile_id: int):
    """Сброс зависшего входа и удаление сессии."""
    task = _login_tasks.get(profile_id)
    if task and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    _clear_session(profile_id)
    sess = _ensure_auth_session(profile_id)
    _drain_queue(sess["sms_q"])
    _drain_queue(sess["pwd_q"])
    _set_auth_step(profile_id, "idle")
    with _conn() as c:
        c.execute(
            "UPDATE profiles SET status=?, last_error='' WHERE id=?",
            (ProfileStatus.PENDING, profile_id),
        )
    return {"ok": True}


@app.post("/api/profiles/{profile_id}/login")
async def login_profile(
    profile_id: int, fresh: bool = False, group_id: int | None = None
):
    _require_vault_unlocked()
    with _conn() as c:
        p = c.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
    if not p:
        raise HTTPException(404, "Профиль не найден")
    if group_id is not None:
        with _conn() as c:
            linked = c.execute(
                "SELECT 1 FROM group_profiles WHERE group_id=? AND profile_id=?",
                (group_id, profile_id),
            ).fetchone()
        if not linked:
            raise HTTPException(400, "Профиль не состоит в этой группе")

    task = _login_tasks.get(profile_id)
    if task and not task.done():
        sess = _ensure_auth_session(profile_id)
        return {
            "ok": True,
            "message": "Вход уже выполняется",
            "auth_step": sess["step"],
            "auth_hint": sess.get("hint", ""),
        }

    sess = _ensure_auth_session(profile_id)
    _drain_queue(sess["sms_q"])
    _drain_queue(sess["pwd_q"])
    _set_auth_step(profile_id, "connecting")

    async def _login():
        try:
            me_id = None
            try:
                me_id = await _login_max(
                    profile_id, p["phone"], fresh=fresh, group_id=group_id
                )
            except Exception:
                if not fresh:
                    append_log(f"Профиль #{profile_id}: сессия не подошла, повтор по SMS…")
                    me_id = await _login_max(
                        profile_id, p["phone"], fresh=True, group_id=group_id
                    )
                else:
                    raise
            with _conn() as c:
                c.execute(
                    "UPDATE profiles SET status=?, last_error='' WHERE id=?",
                    (ProfileStatus.ACTIVE, profile_id),
                )
            _clear_cooldown(profile_id)
            _set_auth_step(profile_id, "idle")
            append_log(f"Профиль #{profile_id} авторизован (id={me_id})")
        except Exception as e:
            err = str(e)
            with _conn() as c:
                c.execute(
                    "UPDATE profiles SET status=?, last_error=? WHERE id=?",
                    (ProfileStatus.NEEDS_REAUTH, err, profile_id),
                )
            _set_auth_step(profile_id, "error")
            append_log(f"Ошибка входа #{profile_id}: {err}")
        finally:
            if _auth_sessions.get(profile_id, {}).get("step") == "connecting":
                _set_auth_step(profile_id, "idle")

    _login_tasks[profile_id] = asyncio.create_task(_login())
    msg = (
        "Новый вход: дождитесь SMS → код → OK. Облачный пароль — если MAX запросит."
        if fresh
        else "Вход запущен. Если придёт SMS — введите код → OK."
    )
    return {"ok": True, "message": msg, "auth_step": "connecting"}


@app.post("/api/profiles/{profile_id}/sms")
async def submit_sms(profile_id: int, body: CodeIn):
    sess = _auth_sessions.get(profile_id)
    if not sess:
        raise HTTPException(404, "Сначала нажмите «Войти»")
    code = body.code.strip()
    if not code:
        raise HTTPException(400, "Введите SMS-код")
    await sess["sms_q"].put(code)
    _set_auth_step(profile_id, "verifying_sms")
    return {"ok": True, "message": "Код отправлен"}


@app.post("/api/profiles/{profile_id}/password")
async def submit_password(profile_id: int, body: CodeIn):
    sess = _auth_sessions.get(profile_id)
    if not sess:
        raise HTTPException(404, "Сначала нажмите «Войти»")
    code = body.code.strip()
    if not code:
        raise HTTPException(400, "Введите облачный пароль")
    await sess["pwd_q"].put(code)
    _set_auth_step(profile_id, "verifying_password")
    return {"ok": True}


@app.patch("/api/profiles/{profile_id}/disable")
async def disable_profile(profile_id: int):
    with _conn() as c:
        c.execute(
            "UPDATE profiles SET status=? WHERE id=?",
            (ProfileStatus.DISABLED, profile_id),
        )
    return {"ok": True}


@app.get("/api/groups")
async def list_groups():
    with _conn() as c:
        rows = c.execute(
            """
            SELECT g.*,
                   COUNT(CASE WHEN gp.is_enabled=1 AND p.status=? THEN 1 END) AS active_count,
                   COUNT(CASE WHEN gp.is_enabled=1 THEN 1 END) AS profiles_count
            FROM groups g
            LEFT JOIN group_profiles gp ON gp.group_id = g.id
            LEFT JOIN profiles p ON p.id = gp.profile_id
            GROUP BY g.id
            ORDER BY g.id
            """,
            (ProfileStatus.ACTIVE,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/groups/{group_id}/profiles")
async def list_group_profiles(group_id: int, offset: int = 0, limit: int = 20):
    with _conn() as c:
        if not c.execute("SELECT 1 FROM groups WHERE id=?", (group_id,)).fetchone():
            raise HTTPException(404, "Группа не найдена")
        total = c.execute(
            "SELECT COUNT(*) n FROM group_profiles WHERE group_id=? AND is_enabled=1",
            (group_id,),
        ).fetchone()["n"]
        rows = c.execute(
            """
            SELECT p.*, gp.order_index FROM profiles p
            JOIN group_profiles gp ON gp.profile_id = p.id
            WHERE gp.group_id=? AND gp.is_enabled=1
            ORDER BY gp.order_index, p.id
            LIMIT ? OFFSET ?
            """,
            (group_id, min(max(limit, 1), 100), max(offset, 0)),
        ).fetchall()
    items = [_profile_auth_view(p) for p in rows]
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@app.post("/api/groups")
async def add_group(body: GroupIn):
    invite = (body.invite_link or "").strip()
    if not invite:
        raise HTTPException(400, "Укажите пригласительную ссылку группы")
    proxy = "" if _is_server_mode() else (body.proxy or "").strip()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO groups (name, max_chat_id, invite_link, proxy) VALUES (?, ?, ?, ?)",
            (
                body.name,
                "",
                invite,
                proxy,
            ),
        )
        gid = cur.lastrowid
    return {"id": gid}


@app.patch("/api/groups/{group_id}")
async def patch_group(group_id: int, body: GroupPatchIn):
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "Нечего обновлять")
    if _is_server_mode() and "proxy" in data:
        data.pop("proxy")
    if "max_chat_id" in data:
        data.pop("max_chat_id")
    with _conn() as c:
        if not c.execute("SELECT 1 FROM groups WHERE id=?", (group_id,)).fetchone():
            raise HTTPException(404, "Группа не найдена")
        if "name" in data and data["name"] is not None:
            c.execute(
                "UPDATE groups SET name=? WHERE id=?",
                (str(data["name"]).strip(), group_id),
            )
        if "max_chat_id" in data:
            c.execute(
                "UPDATE groups SET max_chat_id=? WHERE id=?",
                (str(data["max_chat_id"] or "").strip(), group_id),
            )
        if "invite_link" in data:
            c.execute(
                "UPDATE groups SET invite_link=? WHERE id=?",
                (str(data["invite_link"] or "").strip(), group_id),
            )
        if "proxy" in data:
            proxy = str(data["proxy"] or "").strip()
            c.execute("UPDATE groups SET proxy=? WHERE id=?", (proxy, group_id))
            append_log(
                f"Прокси группы #{group_id}: {'задан' if proxy else 'очищен'}"
            )
        row = c.execute("SELECT * FROM groups WHERE id=?", (group_id,)).fetchone()
    return dict(row)


@app.post("/api/groups/{group_id}/profiles")
async def add_group_profile(group_id: int, body: ProfileIn):
    phone = _normalize_phone(body.phone)
    with _conn() as c:
        g = c.execute("SELECT id FROM groups WHERE id=?", (group_id,)).fetchone()
        if not g:
            raise HTTPException(404, "Группа не найдена")

        row = c.execute("SELECT * FROM profiles WHERE phone=?", (phone,)).fetchone()
        if row:
            pid = row["id"]
            linked = c.execute(
                "SELECT 1 FROM group_profiles WHERE group_id=? AND profile_id=?",
                (group_id, pid),
            ).fetchone()
            if linked:
                raise HTTPException(400, "Этот номер уже в группе")
        else:
            cur = c.execute(
                "INSERT INTO profiles (phone, label, status, proxy) VALUES (?, ?, ?, ?)",
                (
                    phone,
                    body.label.strip(),
                    ProfileStatus.PENDING,
                    (body.proxy or "").strip(),
                ),
            )
            pid = cur.lastrowid
        if body.proxy is not None and str(body.proxy).strip() != "":
            c.execute(
                "UPDATE profiles SET proxy=? WHERE id=?",
                (body.proxy.strip(), pid),
            )

        n = c.execute(
            "SELECT COALESCE(MAX(order_index), -1) n FROM group_profiles WHERE group_id=?",
            (group_id,),
        ).fetchone()["n"]
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, order_index) VALUES (?, ?, ?)",
            (group_id, pid, n + 1),
        )

    _ensure_auth_session(pid)
    append_log(f"Профиль {phone} добавлен в группу #{group_id}")
    return {"id": pid, "phone": phone, "group_id": group_id}


@app.post("/api/groups/{group_id}/profiles/bulk")
async def bulk_add_group_profiles(group_id: int, body: BulkProfilesIn):
    """Импорт phone,label. Пропускает уже существующие в группе."""
    if not body.profiles:
        raise HTTPException(400, "Список профилей пуст")
    if len(body.profiles) > 2000:
        raise HTTPException(400, "Максимум 2000 профилей за раз")

    added, skipped, errors = [], [], []
    with _conn() as c:
        if not c.execute("SELECT id FROM groups WHERE id=?", (group_id,)).fetchone():
            raise HTTPException(404, "Группа не найдена")
        order_n = c.execute(
            "SELECT COALESCE(MAX(order_index), -1) n FROM group_profiles WHERE group_id=?",
            (group_id,),
        ).fetchone()["n"]

        for item in body.profiles:
            try:
                phone = _normalize_phone(item.phone)
                if len(phone) < 8:
                    errors.append({"phone": item.phone, "error": "Некорректный номер"})
                    continue
                row = c.execute(
                    "SELECT * FROM profiles WHERE phone=?", (phone,)
                ).fetchone()
                if row:
                    pid = row["id"]
                    linked = c.execute(
                        "SELECT 1 FROM group_profiles WHERE group_id=? AND profile_id=?",
                        (group_id, pid),
                    ).fetchone()
                    if linked:
                        skipped.append(phone)
                        continue
                else:
                    cur = c.execute(
                        "INSERT INTO profiles (phone, label, status, proxy) VALUES (?, ?, ?, ?)",
                        (
                            phone,
                            (item.label or "").strip(),
                            ProfileStatus.PENDING,
                            (item.proxy or "").strip(),
                        ),
                    )
                    pid = cur.lastrowid
                if (item.proxy or "").strip():
                    c.execute(
                        "UPDATE profiles SET proxy=? WHERE id=?",
                        (item.proxy.strip(), pid),
                    )
                order_n += 1
                c.execute(
                    "INSERT INTO group_profiles (group_id, profile_id, order_index) "
                    "VALUES (?, ?, ?)",
                    (group_id, pid, order_n),
                )
                added.append({"id": pid, "phone": phone})
            except Exception as e:
                errors.append({"phone": getattr(item, "phone", "?"), "error": str(e)})

    for a in added:
        _ensure_auth_session(a["id"])
    append_log(
        f"Массовый импорт в группу #{group_id}: +{len(added)}, пропуск {len(skipped)}, "
        f"ошибок {len(errors)}"
    )
    return {
        "added": len(added),
        "skipped": len(skipped),
        "errors": errors[:50],
        "items": added,
    }


@app.delete("/api/groups/{group_id}")
async def delete_group(group_id: int):
    with _conn() as c:
        if not c.execute("SELECT 1 FROM groups WHERE id=?", (group_id,)).fetchone():
            raise HTTPException(404, "Группа не найдена")
        pids = [
            r["profile_id"]
            for r in c.execute(
                "SELECT profile_id FROM group_profiles WHERE group_id=?", (group_id,)
            ).fetchall()
        ]
        c.execute("DELETE FROM group_profiles WHERE group_id=?", (group_id,))
        c.execute("DELETE FROM groups WHERE id=?", (group_id,))
    for pid in pids:
        _delete_profile_if_orphan(pid)
    append_log(f"Группа #{group_id} удалена")
    return {"ok": True}


@app.delete("/api/groups/{group_id}/profiles/{profile_id}")
async def remove_group_profile(group_id: int, profile_id: int):
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM group_profiles WHERE group_id=? AND profile_id=?",
            (group_id, profile_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Профиль не в этой группе")
        c.execute(
            "DELETE FROM group_profiles WHERE group_id=? AND profile_id=?",
            (group_id, profile_id),
        )
    _delete_profile_if_orphan(profile_id)
    append_log(f"Профиль #{profile_id} удалён из группы #{group_id}")
    return {"ok": True}


@app.get("/api/messages")
async def get_messages():
    msgs = load_message_pool()
    meta = {}
    if MESSAGES_FILE.exists():
        meta["file"] = "active.txt"
        meta["size"] = MESSAGES_FILE.stat().st_size
    with _conn() as c:
        row = c.execute("SELECT loaded_at FROM message_pool LIMIT 1").fetchone()
        if row:
            meta["loaded_at"] = row["loaded_at"]
    return {"count": len(msgs), "messages": msgs, "meta": meta}


@app.post("/api/messages/upload")
async def upload_messages(file: UploadFile = File(...)):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Файл слишком большой (максимум 5 МБ)")
    try:
        n = save_messages_file(content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    append_log(f"Загружено {n} сообщений")
    return {"count": n}


@app.get("/api/settings")
async def get_settings():
    hide = {"api_pin", "telegram_bot_token"}
    out = {k: get_setting(k) for k in DEFAULTS if k not in hide}
    out["api_pin_set"] = _pin_is_set()
    out["telegram_bot_token_set"] = bool(get_setting("telegram_bot_token").strip())
    out["vault"] = vault_status()
    with _conn() as c:
        sched = c.execute("SELECT * FROM campaign_schedule WHERE id=1").fetchone()
    out["schedule"] = dict(sched) if sched else {"enabled": 0, "start_at": None}
    return out


@app.put("/api/settings")
async def update_settings(body: SettingsIn):
    data = body.model_dump(exclude_unset=True)
    if "api_pin" in data:
        pin = data.pop("api_pin")
        if pin is None or str(pin).strip() == "":
            set_setting("api_pin", "")
        else:
            set_setting("api_pin", _hash_pin(str(pin).strip()))
    if "telegram_bot_token" in data:
        tok = data.pop("telegram_bot_token")
        if tok is None or str(tok).strip() == "":
            pass  # не затираем пустой строкой случайно — только явное
        else:
            set_setting("telegram_bot_token", str(tok).strip())
    prev_mode = _message_pick_mode()
    for field, val in data.items():
        set_setting(field, "" if val is None else str(val))
    # legacy-поле = верхняя граница дневного лимита
    if "daily_limit_max" in data and "max_msgs_per_profile_day" not in data:
        set_setting("max_msgs_per_profile_day", str(data["daily_limit_max"]))
    if "message_pick_mode" in data and data["message_pick_mode"] != prev_mode:
        qs_mi = 0
        with _conn() as c:
            row = c.execute("SELECT message_idx FROM queue_state WHERE id=1").fetchone()
            qs_mi = int(row["message_idx"] if row else 0)
        if qs_mi == 0:
            _rebuild_message_bag()
    return {"ok": True}


@app.get("/api/settings/audit")
async def settings_audit(limit: int = 50):
    limit = min(max(limit, 1), 200)
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM settings_audit ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


@app.post("/api/campaign/start")
async def campaign_start():
    _require_vault_unlocked()
    messages = load_message_pool()
    if not messages:
        raise HTTPException(400, "Сначала загрузите файл сообщений")
    if not _active_groups():
        raise HTTPException(400, "Создайте хотя бы одну группу")
    if not _has_active_profiles():
        raise HTTPException(400, "Нет активных профилей — войдите в аккаунты")
    if not _has_sendable_profile():
        raise HTTPException(
            400,
            "Некому отправлять: все профили исчерпали дневной лимит или не авторизованы",
        )
    await _start_worker()
    return {"ok": True, "campaign_id": _current_campaign_id}


@app.post("/api/campaign/stop")
async def campaign_stop():
    await _stop_worker(finish_status="stopped", reason="Остановлено пользователем")
    return {"ok": True}


@app.post("/api/campaign/pause")
async def campaign_pause():
    """Остановить без сброса индексов."""
    await _stop_worker(finish_status="paused", reason="Пауза")
    append_log("Рассылка на паузе")
    return {"ok": True}


@app.post("/api/campaign/reset")
async def campaign_reset():
    """Сбросить прогресс — начать рассылку с начала."""
    if _worker_task and not _worker_task.done():
        raise HTTPException(400, "Остановите рассылку перед сбросом прогресса")
    _reset_queue_progress()
    append_log("Прогресс рассылки сброшен")
    return {"ok": True}


@app.post("/api/campaign/schedule")
async def campaign_schedule(body: ScheduleIn):
    """Запланировать старт. start_at — ISO-8601 (UTC или с offset)."""
    try:
        start_at = _parse_iso_datetime(body.start_at)
    except ValueError as e:
        raise HTTPException(400, f"Некорректная дата: {e}") from e
    if start_at <= datetime.now(timezone.utc):
        raise HTTPException(400, "Время старта должно быть в будущем")
    iso = start_at.isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE campaign_schedule SET start_at=?, enabled=1, "
            "created_at=datetime('now') WHERE id=1",
            (iso,),
        )
    append_log(f"Рассылка запланирована на {iso}")
    return {"ok": True, "start_at": iso, "enabled": True}


@app.delete("/api/campaign/schedule")
async def campaign_schedule_cancel():
    with _conn() as c:
        c.execute(
            "UPDATE campaign_schedule SET enabled=0, start_at=NULL WHERE id=1"
        )
    append_log("Расписание отменено")
    return {"ok": True}


@app.get("/api/campaign/schedule")
async def campaign_schedule_get():
    with _conn() as c:
        row = c.execute("SELECT * FROM campaign_schedule WHERE id=1").fetchone()
    return dict(row) if row else {"enabled": 0, "start_at": None}


@app.post("/api/campaign/retry_failed")
async def campaign_retry_failed():
    """Повторить сообщения, у которых есть failed и нет успешного sent."""
    _require_vault_unlocked()
    if _worker_task and not _worker_task.done():
        raise HTTPException(400, "Сначала остановите текущую рассылку")
    with _conn() as c:
        row = c.execute(
            """
            SELECT MIN(sl.message_idx) AS mi
            FROM send_log sl
            WHERE sl.status='failed'
              AND NOT EXISTS (
                SELECT 1 FROM send_log s2
                WHERE s2.message_idx = sl.message_idx AND s2.status='sent'
              )
            """
        ).fetchone()
    if row is None or row["mi"] is None:
        raise HTTPException(400, "Нет ошибочных сообщений для повтора")
    mi = int(row["mi"])
    with _conn() as c:
        c.execute(
            "UPDATE queue_state SET message_idx=?, profile_idx=0, group_idx=0 WHERE id=1",
            (mi,),
        )
    append_log(f"Повтор ошибок: продолжение с индекса={mi}")
    if not _has_sendable_profile():
        raise HTTPException(400, "Нет доступных профилей для отправки")
    await _start_worker()
    return {"ok": True, "message_idx": mi, "campaign_id": _current_campaign_id}


@app.post("/api/campaign/test")
async def campaign_test():
    """Тестовая отправка первого сообщения первым активным профилем."""
    _require_vault_unlocked()
    messages = load_message_pool()
    if not messages:
        raise HTTPException(400, "Нет сообщений")
    groups = _active_groups()
    if not groups:
        raise HTTPException(400, "Нет групп")
    profile = None
    group = None
    for g in groups:
        profiles = _active_profiles_for_group(g["id"])
        for p in profiles:
            if _is_circuit_open(p["id"]):
                continue
            if _can_send_in_group(p, g["id"]):
                profile, group = p, g
                break
        if profile:
            break
    if not profile or not group:
        raise HTTPException(400, "Нет активного профиля для теста")
    text = messages[0]
    ok = await _send_with_retry(profile, group, text, 0, 0, 0, 0)
    # тест не должен двигать прогресс кампании — откатим индексы если сдвинулись
    # _send_with_retry при успехе пишет message_idx=0 next... actually mi_next=0 means stays?
    # We passed mi_next=0, so it sets message_idx=0. OK.
    if not ok:
        raise HTTPException(502, "Тест не удался — смотрите лог / нужен повторный вход")
    append_log(f"Тест отправки успешен #{profile['id']} → «{group['name']}»")
    return {
        "ok": True,
        "profile_id": profile["id"],
        "phone": profile["phone"],
        "group_id": group["id"],
        "text_preview": text[:80],
    }


@app.get("/api/campaigns")
async def list_campaigns(limit: int = 50):
    limit = min(max(limit, 1), 200)
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM campaigns ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


@app.post("/api/backup")
async def api_backup_now():
    path = backup_database()
    if not path:
        raise HTTPException(500, "Не удалось создать резервную копию")
    return {"ok": True, "file": path.name}


@app.get("/api/backups")
async def api_list_backups():
    BACKUPS.mkdir(parents=True, exist_ok=True)
    files = sorted(BACKUPS.glob("app-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {
        "items": [
            {
                "file": f.name,
                "size": f.stat().st_size,
                "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
            }
            for f in files[:50]
        ]
    }


@app.get("/api/log")
async def get_log():
    return {"lines": _log[-200:]}


@app.get("/api/dashboard")
async def dashboard():
    """Сводка по всем профилям и группам для вкладки Dashboard."""
    with _conn() as c:
        counts = c.execute(
            "SELECT status, COUNT(*) n FROM profiles "
            "WHERE EXISTS (SELECT 1 FROM group_profiles gp WHERE gp.profile_id = profiles.id) "
            "GROUP BY status"
        ).fetchall()
        profiles = c.execute(
            """
            SELECT p.*,
                   GROUP_CONCAT(g.name, ', ') AS group_names,
                   MIN(g.id) AS primary_group_id
            FROM profiles p
            JOIN group_profiles gp ON gp.profile_id = p.id AND gp.is_enabled=1
            JOIN groups g ON g.id = gp.group_id
            GROUP BY p.id
            ORDER BY
              CASE p.status
                WHEN 'needs_reauth' THEN 0
                WHEN 'pending' THEN 1
                WHEN 'active' THEN 2
                ELSE 3
              END,
              p.id
            LIMIT 500
            """
        ).fetchall()
        groups_n = c.execute("SELECT COUNT(*) n FROM groups").fetchone()["n"]
        sent_today = c.execute(
            "SELECT COUNT(*) n FROM send_log WHERE date(sent_at)=date('now') AND status='sent'"
        ).fetchone()["n"]
        failed_today = c.execute(
            "SELECT COUNT(*) n FROM send_log WHERE date(sent_at)=date('now') AND status='failed'"
        ).fetchone()["n"]
    items = []
    for p in profiles:
        d = _profile_auth_view(p)
        d["circuit_open"] = _is_circuit_open(p["id"])
        items.append(d)
    return {
        "counts": {r["status"]: r["n"] for r in counts},
        "groups_count": groups_n,
        "sent_today": sent_today,
        "failed_today": failed_today,
        "circuit_open": _circuit_open_count(),
        "items": items,
    }


@app.get("/api/send_log")
async def get_send_log(
    offset: int = 0,
    limit: int = 50,
    q: str = "",
    status: str = "",
):
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    where = ["1=1"]
    params: list[Any] = []
    if status.strip():
        where.append("sl.status = ?")
        params.append(status.strip())
    if q.strip():
        where.append(
            "(p.phone LIKE ? OR p.label LIKE ? OR g.name LIKE ? OR sl.error LIKE ? "
            "OR CAST(sl.profile_id AS TEXT) LIKE ?)"
        )
        like = f"%{q.strip()}%"
        params.extend([like, like, like, like, like])
    where_sql = " AND ".join(where)
    with _conn() as c:
        total = c.execute(
            f"""
            SELECT COUNT(*) n
            FROM send_log sl
            LEFT JOIN profiles p ON p.id = sl.profile_id
            LEFT JOIN groups g ON g.id = sl.group_id
            WHERE {where_sql}
            """,
            params,
        ).fetchone()["n"]
        rows = c.execute(
            f"""
            SELECT sl.*, p.phone, p.label, g.name AS group_name
            FROM send_log sl
            LEFT JOIN profiles p ON p.id = sl.profile_id
            LEFT JOIN groups g ON g.id = sl.group_id
            WHERE {where_sql}
            ORDER BY sl.id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "q": q,
        "status": status,
    }


try:
    from server.app.register import register_server

    register_server(app)
except ImportError:
    pass


if __name__ == "__main__":
    _self_check_round_robin()
    init_db()

    def _handle_signal(signum, _frame):
        global _shutting_down
        if _shutting_down:
            return
        _shutting_down = True
        append_log(f"Сигнал {signum}: шифрование сессий и выход…")
        _encrypt_all_sessions()
        sys.exit(0)

    with contextlib.suppress(ValueError, OSError):
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    open_browser = "--no-browser" not in sys.argv
    if open_browser:

        def _open_browser_when_ready() -> None:
            for _ in range(40):
                try:
                    urlopen(APP_URL, timeout=1)
                    webbrowser.open(APP_URL)
                    return
                except (URLError, OSError):
                    time.sleep(0.25)
            webbrowser.open(APP_URL)

        threading.Thread(target=_open_browser_when_ready, daemon=True).start()

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
