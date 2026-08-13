"""Global admin pacing settings → per-tenant SQLite copy (ADR 007).

Allowlist only. Secrets and per-tenant ops keys are never copied.
"""

from __future__ import annotations

import logging
from typing import Mapping

logger = logging.getLogger(__name__)

# Explicit allowlist (pacing / antiban / human-rhythm). Do not derive by
# subtracting a denylist from DEFAULTS — new keys must be classified in tests.
GLOBAL_PACING_SETTING_KEYS = frozenset(
    {
        "delay_min_sec",
        "delay_max_sec",
        "max_msgs_per_profile_day",
        "daily_limit_min",
        "daily_limit_max",
        "jitter_percent",
        "message_pick_mode",
        "campaign_goal",
        "warmup_enabled",
        "warmup_days",
        "cooldown_reauth_hours",
        "cooldown_fail_hours",
        "human_rhythm_enabled",
        "send_windows_weekday",
        "send_windows_weekend",
        "day_skip_percent",
        "role_plan_enabled",
        "role_active_percent",
        "role_quiet_percent",
        "role_active_min",
        "role_active_max",
        "role_quiet_limit",
        "human_pauses_enabled",
        "short_pause_chance",
        "short_pause_min_sec",
        "short_pause_max_sec",
        "long_pause_chance",
        "long_pause_min_sec",
        "long_pause_max_sec",
        "break_after_n",
        "break_min_sec",
        "break_max_sec",
        "jitter_morning_percent",
        "jitter_evening_percent",
        "warmup_start_min",
        "warmup_start_max",
        "lazy_day_percent",
        "lazy_day_factor",
        "human_presence_enabled",
        "presence_history_chance",
        "presence_read_chance",
        "presence_react_chance",
        "presence_reactions",
        "presence_idle_chance",
        "human_texts_enabled",
        "text_dedupe_enabled",
        "text_similarity_max",
        "text_dedupe_window",
        "text_length_variety",
        "timezone_offset_hours",
        "circuit_break_minutes",
        "cooldown_fail_max_hours",
        "cooldown_disable_after_fails",
    }
)

# Secrets, campaign auto-resume, and per-tenant ops — never copy from global.
GLOBAL_PACING_NEVER_COPY = frozenset(
    {
        "api_pin",
        "telegram_bot_token",
        "telegram_chat_id",
        "webhook_url",
        "auto_run",
        "auto_run_pool_reset_day",
        "worker_pool_size",
        "backup_interval_hours",
        "password_max_attempts",
    }
)


def filter_pacing_updates(data: Mapping[str, object]) -> dict[str, str]:
    """Keep allowlisted keys only; stringify values like set_setting."""
    out: dict[str, str] = {}
    for key, val in data.items():
        if key in GLOBAL_PACING_SETTING_KEYS:
            out[key] = "" if val is None else str(val)
    return out


def should_seed_tenant_pacing() -> bool:
    from app.runtime import main as m
    from app.tenant import get_tenant_id, use_global_data

    if not m._is_server_mode():
        return False
    return (not use_global_data()) and get_tenant_id() is not None


def iter_tenant_ids(root) -> list[int]:
    tenants_root = root / "data" / "tenants"
    if not tenants_root.is_dir():
        return []
    ids: list[int] = []
    for entry in tenants_root.iterdir():
        if entry.is_dir() and entry.name.isdigit() and (entry / "app.db").is_file():
            ids.append(int(entry.name))
    return ids


def read_global_pacing_values() -> dict[str, str]:
    """Read allowlisted keys from global sqlite. Empty if global DB is missing."""
    from app.runtime import main as m

    path = m.ROOT / "data" / "global" / "app.db"
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    try:
        conn = m._global_conn()
        for key in GLOBAL_PACING_SETTING_KEYS:
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
            if row is not None:
                out[key] = row["value"]
    except Exception:
        return {}
    return out


def seed_tenant_settings_from_global(conn) -> None:
    """Overwrite allowlisted keys on a fresh tenant sqlite from global, if present."""
    values = read_global_pacing_values()
    if not values:
        return
    for key, val in values.items():
        if key not in GLOBAL_PACING_SETTING_KEYS:
            continue
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, val),
        )


def propagate_global_pacing_settings(values: Mapping[str, str]) -> int:
    """Copy allowlisted key/values into every tenant SQLite; invalidate cache.

    Returns the number of tenant DBs updated.
    """
    from app.runtime import main as m
    from app.tenant import tenant_scope

    filtered = {
        k: str(v)
        for k, v in values.items()
        if k in GLOBAL_PACING_SETTING_KEYS
    }
    if not filtered:
        return 0
    updated = 0
    for tid in iter_tenant_ids(m.ROOT):
        try:
            with tenant_scope(tenant_id=tid, role="admin"):
                with m._conn() as c:
                    for key, val in filtered.items():
                        c.execute(
                            "INSERT INTO settings (key, value) VALUES (?, ?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (key, val),
                        )
                with m._settings_cache_lock:
                    for key, val in filtered.items():
                        m._settings_cache[("tenant", tid, key)] = val
            updated += 1
        except Exception:
            logger.exception("pacing settings copy failed tenant_id=%s", tid)
    return updated
