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
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

import antiban_core

from app.campaign_runtime import REGISTRY, RUNTIME

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
        from app.config import is_server_mode

        return is_server_mode()
    except ImportError:
        return False


def _resolve_data_dir() -> Path:
    override = os.environ.get("MAX_DATA", "").strip()
    if override:
        return Path(override)
    if _is_server_mode():
        from app.tenant import get_effective_data_dir

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
    # Антибан: паузы, лимиты, один отправитель (scale: group rotation + 1 proxy/group)
    "delay_min_sec": "5",
    "delay_max_sec": "15",
    "max_msgs_per_profile_day": "10",  # legacy; фактический лимит — daily_limit_min/max
    "daily_limit_min": "5",
    "daily_limit_max": "10",
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
    "day_skip_percent": "40",
    "role_plan_enabled": "1",
    "role_active_percent": "30",
    "role_quiet_percent": "30",
    "role_active_min": "5",
    "role_active_max": "10",
    "role_quiet_limit": "1",
    # Человечность C: неровные паузы, перерыв после N, разный jitter
    "human_pauses_enabled": "1",
    "short_pause_chance": "8",
    "short_pause_min_sec": "30",
    "short_pause_max_sec": "50",
    "long_pause_chance": "3",
    "long_pause_min_sec": "120",
    "long_pause_max_sec": "300",
    "break_after_n": "8",
    "break_min_sec": "600",
    "break_max_sec": "1200",
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
    # После Старта — автовозобновление на следующий день без ручного запуска
    "auto_run": "0",
    "auto_run_pool_reset_day": "",
}

_APP_KEY_PATH = DATA / ".app_key"
_APP_SALT_PATH = DATA / ".app_salt"
_APP_VAULT_PATH = DATA / ".app_vault"
BACKUPS = DATA / "backups"

_claim_lock = threading.Lock()
_app_started_at: float | None = None
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
_auth_sessions: dict[Any, dict[str, Any]] = {}
_login_tasks: dict[Any, asyncio.Task] = {}
_settings_cache: dict = {}
_settings_cache_lock = threading.Lock()
_rate_counters: dict[str, list[float]] = defaultdict(list)
_fernet: Fernet | None = None
_vault_unlocked = False


def reset_test_runtime() -> None:
    """Сброс in-memory состояния между pytest-тестами (MAX_TEST=1)."""
    global _fernet, _vault_unlocked
    from app import sqlite_backend

    sqlite_backend.reset_connections()
    _fernet = None
    _vault_unlocked = False
    REGISTRY.reset_test()
    with _settings_cache_lock:
        _settings_cache.clear()
    with _log_lock:
        _log.clear()
    _auth_sessions.clear()
    _login_tasks.clear()
    _rate_counters.clear()
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
    
    now = _local_now()
    wall = time.time()
    with _conn() as c:
        rows = c.execute("SELECT * FROM antiban_state").fetchall()
    for row in rows:
        pid = int(row["profile_id"])
        burst = int(row["burst_count"] or 0)
        if burst > 0:
            RUNTIME.human_burst_count[pid] = burst
        raw_break = row["break_until"]
        if raw_break:
            try:
                until = datetime.fromisoformat(str(raw_break))
                if until.tzinfo is not None:
                    until = until.replace(tzinfo=None)
                if until > now:
                    RUNTIME.human_break_until[pid] = until
            except ValueError:
                pass
        errs = int(row["consecutive_errors"] or 0)
        if errs > 0:
            RUNTIME.consecutive_errors[pid] = errs
        opened = row["circuit_opened_at"]
        if opened is not None and errs >= MAX_CONSECUTIVE_ERRORS:
            try:
                opened_f = float(opened)
            except (TypeError, ValueError):
                continue
            # wall-clock; если срок вышел — не восстанавливаем
            mins = max(1.0, _setting_float("circuit_break_minutes", float(CIRCUIT_BREAK_MINUTES)))
            if wall - opened_f < mins * 60:
                RUNTIME.circuit_opened_at[pid] = opened_f
            else:
                RUNTIME.consecutive_errors.pop(pid, None)


def _persist_antiban_profile(profile_id: int) -> None:
    burst = RUNTIME.human_burst_count.get(profile_id, 0)
    until = RUNTIME.human_break_until.get(profile_id)
    errs = RUNTIME.consecutive_errors.get(profile_id, 0)
    opened = RUNTIME.circuit_opened_at.get(profile_id)
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


def _scoped_sqlite_conn() -> sqlite3.Connection:
    """Settings/messages SQLite: tenant scope or global admin (server mode)."""
    if _is_server_mode():
        from app.tenant import use_global_data

        if use_global_data():
            return _global_conn()
    return _conn()


def _settings_cache_scope() -> tuple[str, int | None]:
    if not _is_server_mode():
        return ("local", None)
    from app.tenant import get_tenant_id, use_global_data

    if use_global_data():
        return ("global", None)
    return ("tenant", get_tenant_id())


def get_setting(key: str) -> str:
    scope = _settings_cache_scope()
    cache_key = (scope[0], scope[1], key)
    with _settings_cache_lock:
        if cache_key in _settings_cache:
            return _settings_cache[cache_key]
    conn = _scoped_sqlite_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    val = row["value"] if row else DEFAULTS.get(key, "")
    with _settings_cache_lock:
        _settings_cache[cache_key] = val
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
    conn = _scoped_sqlite_conn()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    scope = _settings_cache_scope()
    cache_key = (scope[0], scope[1], key)
    with _settings_cache_lock:
        _settings_cache[cache_key] = value
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




def _backups_dir() -> Path:
    return _resolve_data_dir() / "backups"



def _messages_file() -> Path:
    if _is_server_mode():
        from app.tenant import use_global_data

        if use_global_data():
            return ROOT / "data" / "global" / "messages" / "active.txt"
        return _resolve_data_dir() / "messages" / "active.txt"
    return MESSAGES_FILE

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
    _ensure_vault_unlocked()
    has_legacy = _APP_KEY_PATH.exists()
    return {
        "unlocked": bool(_vault_unlocked and _fernet is not None),
        "protected": False,
        "legacy": has_legacy,
        "needs_setup": False,
    }


def _ensure_vault_unlocked() -> None:
    """Auto-unlock via .app_key; no user password in server/desktop panel."""
    global _fernet, _vault_unlocked
    if _vault_unlocked and _fernet is not None:
        return
    DATA.mkdir(parents=True, exist_ok=True)
    SESSIONS.mkdir(parents=True, exist_ok=True)
    if _APP_SALT_PATH.exists():
        _APP_SALT_PATH.unlink(missing_ok=True)
        _APP_VAULT_PATH.unlink(missing_ok=True)
        append_log("Хранилище: режим с паролем отключён, используется .app_key")
    if not _APP_KEY_PATH.exists():
        _APP_KEY_PATH.write_bytes(Fernet.generate_key())
    try:
        _fernet = Fernet(_APP_KEY_PATH.read_bytes())
        _vault_unlocked = True
    except Exception as e:
        append_log(f"Хранилище: не удалось загрузить .app_key: {e}")


def _try_legacy_unlock() -> None:
    _ensure_vault_unlocked()


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
    _ensure_vault_unlocked()
    if not (_vault_unlocked and _fernet is not None):
        raise HTTPException(423, "Хранилище сессий недоступно")


def _vault_ready_for_send() -> bool:
    st = vault_status()
    return not st["needs_setup"] and bool(st["unlocked"])


def _auto_run_enabled() -> bool:
    return get_setting("auto_run") == "1"


def _reset_message_pool_progress() -> None:
    n = len(load_message_pool())
    with _conn() as c:
        c.execute("UPDATE queue_state SET message_idx=0 WHERE id=1")
    _rebuild_message_bag(n)


def _prepare_auto_resume_pool() -> bool:
    """message_pool: на новый день сбросить пул; в тот же день после исчерпания — ждать."""
    if _campaign_goal() != "message_pool":
        return True
    msgs = load_message_pool()
    if not msgs:
        return False
    with _conn() as c:
        qs = c.execute("SELECT message_idx FROM queue_state WHERE id=1").fetchone()
    mi = int(qs["message_idx"] if qs else 0)
    if mi < len(msgs):
        return True
    today = _local_today().isoformat()
    if get_setting("auto_run_pool_reset_day") == today:
        return False
    set_setting("auto_run_pool_reset_day", today)
    _reset_message_pool_progress()
    return True


async def _try_auto_resume(*, log_prefix: str = "Автовозобновление") -> bool:
    if not _auto_run_enabled():
        return False
    if RUNTIME.worker_busy():
        return False
    if not _vault_ready_for_send():
        return False
    if not load_message_pool():
        return False
    if not _prepare_auto_resume_pool():
        return False
    if not _has_sendable_profile():
        return False
    append_log(f"{log_prefix}: старт рассылки")
    await _start_worker(record_campaign=True)
    return True


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


def _normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "")
    if phone.startswith("8") and len(phone) == 11:
        phone = "+7" + phone[1:]
    elif phone.startswith("7") and len(phone) == 11:
        phone = "+" + phone
    elif not phone.startswith("+"):
        phone = "+" + phone.lstrip("+")
    return phone


def _auth_session_key(profile_id: int) -> Any:
    if _is_server_mode():
        from app.tenant import get_tenant_id

        return (get_tenant_id(), profile_id)
    return profile_id


def _ensure_auth_session(profile_id: int) -> dict[str, Any]:
    key = _auth_session_key(profile_id)
    if key not in _auth_sessions:
        _auth_sessions[key] = {
            "sms_q": asyncio.Queue(),
            "pwd_q": asyncio.Queue(),
            "step": "idle",
            "hint": "",
        }
    return _auth_sessions[key]


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
    sess = _auth_sessions.get(_auth_session_key(int(d["id"])), {})
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
        step = _auth_sessions.get(_auth_session_key(profile_id), {}).get("step", "connecting")
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


def _ensure_role_cycle_anchor() -> None:
    """Первый запуск кампании — якорь 3-дневной ротации ролей (без сброса)."""
    if get_setting("role_cycle_anchor"):
        return
    set_setting("role_cycle_anchor", _local_today().isoformat())


def _role_cycle_anchor() -> date | None:
    raw = get_setting("role_cycle_anchor")
    if raw:
        try:
            return date.fromisoformat(str(raw).strip()[:10])
        except ValueError:
            pass
    with _conn() as c:
        row = c.execute(
            "SELECT MIN(started_at) AS t FROM campaigns WHERE started_at IS NOT NULL"
        ).fetchone()
    if not row or not row["t"]:
        return None
    val = str(row["t"]).strip()
    try:
        if "T" in val or "+" in val or val.endswith("Z"):
            dt = _parse_iso_datetime(val)
        else:
            dt = datetime.strptime(val[:19], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        offset = float(get_setting("timezone_offset_hours") or DEFAULTS["timezone_offset_hours"])
        return dt.astimezone(timezone(timedelta(hours=offset))).date()
    except (ValueError, TypeError):
        try:
            return date.fromisoformat(val[:10])
        except ValueError:
            return None


def _role_cycle_day() -> int:
    anchor = _role_cycle_anchor()
    if anchor is None:
        return 0
    return (_local_today() - anchor).days % 3


def _role_percent_mode() -> bool:
    return _setting_float("role_active_percent", 0.0) > 0.0


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


_PROXY_RECHECK_SEC = 300.0
_proxy_bad_until: dict[str, tuple[float, str]] = {}
_tg_notify_at: dict[str, float] = {}
_TG_DEDUPE_SEC = 300.0


def _group_proxy_raw(group_id: int) -> str:
    with _conn() as c:
        row = c.execute("SELECT proxy FROM groups WHERE id=?", (group_id,)).fetchone()
    if not row:
        return ""
    try:
        return (row["proxy"] or "").strip()
    except (KeyError, IndexError):
        return ""


def _group_has_proxy_configured(group: sqlite3.Row | dict[str, Any]) -> bool:
    raw = ""
    try:
        raw = (group["proxy"] or "").strip()
    except (KeyError, IndexError, TypeError):
        raw = _group_proxy_raw(int(group["id"]))
    return bool(antiban_core.parse_proxy_list(raw))


def _proxy_host_label(proxy_url: str) -> str:
    return proxy_url.split("@")[-1] if proxy_url else ""


def _validate_proxy_for_group(
    group: sqlite3.Row | dict[str, Any],
    profile_id: int | None,
) -> tuple[bool, str]:
    """True = можно работать (прокси не задан или доступен)."""
    gid = int(group["id"])
    raw = _group_proxy_raw(gid)
    if not antiban_core.parse_proxy_list(raw):
        return True, ""
    if profile_id is not None:
        urls = [u for u in [_group_proxy(gid, profile_id)] if u]
    else:
        urls = antiban_core.parse_proxy_list(raw)
    last_err = ""
    gname = str(group["name"])
    for proxy_url in urls:
        key = f"{gid}:{_proxy_host_label(proxy_url)}"
        now = time.time()
        bad = _proxy_bad_until.get(key)
        if bad and now < bad[0]:
            last_err = bad[1]
            continue
        ok, err = antiban_core.check_proxy(proxy_url)
        if ok:
            _proxy_bad_until.pop(key, None)
            return True, ""
        _proxy_bad_until[key] = (now + _PROXY_RECHECK_SEC, err)
        last_err = err
        append_log(
            f"Прокси недоступен: группа «{gname}» "
            f"({_proxy_host_label(proxy_url)}): {err}"
        )
        _schedule_telegram(
            "Прокси недоступен",
            [
                f"Группа: {gname} (#{gid})",
                f"Прокси: {_proxy_host_label(proxy_url)}",
                f"Ошибка: {err}",
            ],
            dedupe_key=f"proxy:{key}",
        )
    return False, last_err or "прокси недоступен"


async def _preflight_group_proxies() -> None:
    for group in _active_groups():
        if not _group_has_proxy_configured(group):
            continue
        await asyncio.to_thread(_validate_proxy_for_group, group, None)


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


def _is_in_human_break(profile_id: int) -> bool:
    until = RUNTIME.human_break_until.get(profile_id)
    if not until:
        return False
    if _local_now() >= until:
        RUNTIME.human_break_until.pop(profile_id, None)
        _persist_antiban_profile(profile_id)
        return False
    return True


def _note_human_burst(profile_id: int) -> None:
    if not _setting_truthy("human_pauses_enabled", "1"):
        return
    n = max(0, _setting_int("break_after_n", 8))
    if n <= 0:
        return
    burst = RUNTIME.human_burst_count.get(profile_id, 0) + 1
    if burst < n:
        RUNTIME.human_burst_count[profile_id] = burst
        _persist_antiban_profile(profile_id)
        return
    RUNTIME.human_burst_count[profile_id] = 0
    blo = float(_setting_int("break_min_sec", 600))
    bhi = float(_setting_int("break_max_sec", 1200))
    blo, bhi = antiban_core.clamp_range(blo, bhi)
    secs = random.uniform(blo, bhi)
    until = _local_now() + timedelta(seconds=secs)
    RUNTIME.human_break_until[profile_id] = until
    _persist_antiban_profile(profile_id)
    append_log(
        f"Перерыв аккаунта #{profile_id} после {n} сообщений: "
        f"~{int(secs // 60)} мин (до {until.strftime('%H:%M')})"
    )


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
        for until in RUNTIME.human_break_until.values()
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



from app.sqlite_backend import (
    _conn,
    _db_path,
    _global_conn,
    _global_db_path,
    _migrate_antiban_defaults,
    _reset_db_conn,
    _table_columns,
    init_db,
)
from app.campaign_queue import (
    _ensure_message_bag,
    _get_message_bag,
    _pick_next_message,
    _rebuild_message_bag,
    _return_to_message_bag,
    _set_message_bag,
)
from app.campaign_query import (
    _active_groups,
    _active_profiles_for_group,
    _ensure_group_role_plan,
)

from app.campaign_worker import (
    begin_campaign as _begin_campaign,
    finish_campaign as _finish_campaign,
    notify_campaign_end as _notify_campaign_end,
    schedule_telegram as _schedule_telegram,
    scheduler_loop as _scheduler_loop,
    start_worker as _start_worker,
    stop_all_workers as _stop_all_workers,
    stop_worker as _stop_worker,
    watchdog_loop as _watchdog_loop,
    worker_shutdown as _worker_shutdown,
)


def backup_database() -> Path | None:
    """Снимок SQLite в data/backups/. Возвращает путь или None."""
    try:
        BACKUPS.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = BACKUPS / f"app-{ts}.db"
        # checkpoint WAL перед копированием
        with _conn() as c:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        shutil.copy2(_db_path(), dest)
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


def _sqlite_reset_running_campaigns(db_path: Path) -> None:
    if not db_path.is_file():
        return
    with sqlite3.connect(db_path) as c:
        c.execute(
            "UPDATE campaigns SET status='stopped', finished_at=datetime('now'), "
            "reason='Сервер перезапущен' WHERE status='running'"
        )
        c.execute("UPDATE queue_state SET running=0 WHERE id=1")


def _tenant_sqlite_paths() -> list[Path]:
    paths: list[Path] = []
    if _is_server_mode():
        tenants_root = ROOT / "data" / "tenants"
        if tenants_root.is_dir():
            for entry in tenants_root.iterdir():
                if entry.is_dir():
                    db = entry / "app.db"
                    if db.is_file():
                        paths.append(db)
        for extra in (ROOT / "data" / "global" / "app.db", ROOT / "data" / "app.db"):
            if extra.is_file():
                paths.append(extra)
    else:
        paths.append(_db_path())
    return paths


def _reset_auth_on_startup() -> None:
    _auth_sessions.clear()
    _login_tasks.clear()
    for db_path in _tenant_sqlite_paths():
        _sqlite_reset_running_campaigns(db_path)
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
    RUNTIME.touch_activity()


def _on_success(profile_id: int) -> None:
    RUNTIME.consecutive_errors.pop(profile_id, None)
    RUNTIME.circuit_opened_at.pop(profile_id, None)
    _persist_antiban_profile(profile_id)


def _on_error(profile_id: int) -> None:
    n = RUNTIME.consecutive_errors.get(profile_id, 0) + 1
    RUNTIME.consecutive_errors[profile_id] = n
    mins = max(1.0, _setting_float("circuit_break_minutes", float(CIRCUIT_BREAK_MINUTES)))
    if n >= MAX_CONSECUTIVE_ERRORS:
        RUNTIME.circuit_opened_at.setdefault(profile_id, time.time())
        append_log(
            f"Автопауза: профиль #{profile_id} отключён на "
            f"{int(mins)} мин после {n} ошибок подряд"
        )
    _persist_antiban_profile(profile_id)


def _is_circuit_open(profile_id: int) -> bool:
    count = RUNTIME.consecutive_errors.get(profile_id, 0)
    if count < MAX_CONSECUTIVE_ERRORS:
        return False
    opened = RUNTIME.circuit_opened_at.get(profile_id, 0.0)
    mins = max(1.0, _setting_float("circuit_break_minutes", float(CIRCUIT_BREAK_MINUTES)))
    if time.time() - opened > mins * 60:
        _on_success(profile_id)
        append_log(f"Автопауза: профиль #{profile_id} снова доступен")
        return False
    return True


def _circuit_open_count() -> int:
    total = 0
    for _, rt in REGISTRY.worker_items():
        total += sum(
            1 for pid in list(rt.consecutive_errors) if _is_circuit_open_for(pid, rt)
        )
    if not REGISTRY.worker_items():
        total += sum(
            1 for pid in list(RUNTIME.consecutive_errors) if _is_circuit_open(pid)
        )
    return total


def _is_circuit_open_for(profile_id: int, rt) -> bool:
    count = rt.consecutive_errors.get(profile_id, 0)
    if count < MAX_CONSECUTIVE_ERRORS:
        return False
    opened = rt.circuit_opened_at.get(profile_id, 0.0)
    mins = max(1.0, _setting_float("circuit_break_minutes", float(CIRCUIT_BREAK_MINUTES)))
    return time.time() - opened <= mins * 60


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
    from app.campaign_send import send_with_retry

    return await send_with_retry(
        profile,
        group,
        text,
        mi,
        pi,
        gi_next,
        mi_next,
        advance_queue=advance_queue,
    )


async def _backup_loop() -> None:
    last_backup = 0.0
    while True:
        await asyncio.sleep(60)
        if REGISTRY.app.shutting_down:
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
        "auto_run": _auto_run_enabled(),
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
    global _app_started_at
    init_db()
    _load_log_from_db()
    _load_antiban_state()
    _try_legacy_unlock()
    _reset_auth_on_startup()
    _app_started_at = time.time()
    if not _is_test_mode():
        RUNTIME.watchdog_task = asyncio.create_task(_watchdog_loop())
        RUNTIME.scheduler_task = asyncio.create_task(_scheduler_loop())
        RUNTIME.backup_task = asyncio.create_task(_backup_loop())
        if _is_server_mode():
            from app.ops_monitor import ops_alert_loop
            from app.subscription_jobs import subscription_lifecycle_loop

            RUNTIME.ops_alert_task = asyncio.create_task(ops_alert_loop())
            RUNTIME.subscription_task = asyncio.create_task(subscription_lifecycle_loop())

        async def _startup_auto_resume() -> None:
            await asyncio.sleep(2)
            await _try_auto_resume(log_prefix="Автозапуск")

        asyncio.create_task(_startup_auto_resume())
    try:
        yield
    finally:
        REGISTRY.app.shutting_down = True
        if not _is_test_mode():
            for task in (
                RUNTIME.watchdog_task,
                RUNTIME.scheduler_task,
                RUNTIME.backup_task,
                RUNTIME.ops_alert_task,
                RUNTIME.subscription_task,
            ):
                if task:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            RUNTIME.watchdog_task = RUNTIME.scheduler_task = RUNTIME.backup_task = None
            RUNTIME.ops_alert_task = RUNTIME.subscription_task = None
        await _stop_all_workers(finish_status="stopped", reason="Остановка сервера")
        _encrypt_all_sessions()


def _encrypt_all_sessions() -> None:
    for key in list(_auth_sessions.keys()):
        profile_id = key[1] if isinstance(key, tuple) else key
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
try:
    from app.register import register_server

    register_server(app)
except ImportError:
    pass


if __name__ == "__main__":
    _self_check_round_robin()
    init_db()

    def _handle_signal(signum, _frame):
        if REGISTRY.app.shutting_down:
            return
        REGISTRY.app.shutting_down = True
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
