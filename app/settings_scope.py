"""Global admin pacing settings → per-tenant SQLite copy (ADR 007).

Allowlist only. Secrets and per-tenant ops keys are never copied.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Mapping

logger = logging.getLogger(__name__)

LEGACY_PRESENCE_SETTING_KEYS = (
    "human_presence_enabled",
    "presence_history_chance",
    "presence_read_chance",
    "presence_react_chance",
    "presence_reactions",
    "presence_idle_chance",
)
GLOBAL_PACING_LEGACY_INACTIVE = frozenset(LEGACY_PRESENCE_SETTING_KEYS)
RETIRED_SCHEDULE_SETTING_KEYS = frozenset(
    {
        "max_msgs_per_profile_day",
        "daily_limit_min",
        "daily_limit_max",
        "campaign_goal",
        "warmup_enabled",
        "warmup_days",
        "warmup_start_min",
        "warmup_start_max",
        "human_rhythm_enabled",
        "day_skip_percent",
        "lazy_day_percent",
        "lazy_day_factor",
        "role_plan_enabled",
        "role_active_percent",
        "role_quiet_percent",
        "role_active_min",
        "role_active_max",
        "role_quiet_limit",
    }
)

# Explicit allowlist (pacing / antiban / human-rhythm). Do not derive by
# subtracting a denylist from DEFAULTS — new keys must be classified in tests.
GLOBAL_PACING_SETTING_KEYS = frozenset(
    {
        "delay_min_sec",
        "delay_max_sec",
        "jitter_percent",
        "message_pick_mode",
        "cooldown_reauth_hours",
        "cooldown_fail_hours",
        "send_windows_weekday",
        "send_windows_weekend",
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


@dataclass(frozen=True)
class PacingFanoutReport:
    """Durable result of one global policy revision fan-out."""

    desired_revision: int
    applied: list[int]
    failed: dict[int, str]

    def as_dict(self) -> dict[str, object]:
        applied_revisions = {"global": self.desired_revision}
        applied_revisions.update(
            {f"tenant:{tenant_id}": self.desired_revision for tenant_id in self.applied}
        )
        return {
            "desired_revision": self.desired_revision,
            "applied_revision": applied_revisions,
            "applied_tenants": list(self.applied),
            "failed_tenants": [
                {"tenant_id": tenant_id, "safe_error": error}
                for tenant_id, error in sorted(self.failed.items())
            ],
            "partial": bool(self.failed),
        }


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
    from app.domain.contracts import resolve_data_root

    tenants_root = resolve_data_root(
        {"MAX_DATA": os.environ.get("MAX_DATA", ""), "ROOT": root}
    ) / "tenants"
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

    path = m._resolve_data_root() / "global" / "app.db"
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


def _policy_scope_key(m) -> str:
    if not m._is_server_mode():
        return "local"
    from app.tenant import get_tenant_id, use_global_data

    if use_global_data():
        return "global"
    tenant_id = get_tenant_id()
    return f"tenant:{tenant_id}" if tenant_id is not None else "local"


def _safe_actor(actor: object) -> str:
    return str(actor or "").strip()[:64]


def _update_settings_cache(m, values: Mapping[str, str]) -> None:
    scope = m._settings_cache_scope()
    with m._settings_cache_lock:
        for key, value in values.items():
            m._settings_cache[(scope[0], scope[1], key)] = value


def _apply_pacing_revision_to_connection(
    conn,
    *,
    scope_key: str,
    values: Mapping[str, str],
    actor: object,
    source_revision: int | None = None,
) -> int:
    """Apply one policy version atomically inside one SQLite scope."""

    from app.runtime import main as m
    old_values: dict[str, str] = {}
    for key, value in values.items():
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        old_values[key] = str(row["value"]) if row is not None else ""
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    payload = json.dumps(
        dict(sorted(values.items())),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    cursor = conn.execute(
        "INSERT INTO policy_versions "
        "(scope_key, source_revision, values_json, actor, effective_rule) "
        "VALUES (?, ?, ?, ?, 'next_approved_boundary')",
        (scope_key, source_revision, payload, _safe_actor(actor)),
    )
    local_revision = int(cursor.lastrowid)
    desired_revision = (
        int(source_revision) if source_revision is not None else local_revision
    )
    conn.execute(
        "INSERT INTO policy_scope_state "
        "(scope_key, desired_revision, applied_revision) VALUES (?, ?, ?) "
        "ON CONFLICT(scope_key) DO UPDATE SET "
        "desired_revision=excluded.desired_revision, "
        "applied_revision=excluded.applied_revision, "
        "updated_at=CURRENT_TIMESTAMP",
        (scope_key, desired_revision, desired_revision),
    )

    for key, value in values.items():
        old_value = old_values[key]
        if old_value != value:
            conn.execute(
                "INSERT INTO settings_audit (key, old_value, new_value) VALUES (?, ?, ?)",
                (key, m._audit_mask(key, old_value), m._audit_mask(key, value)),
            )
    conn.execute(
        "DELETE FROM settings_audit WHERE id NOT IN "
        "(SELECT id FROM settings_audit ORDER BY id DESC LIMIT 1000)"
    )
    return desired_revision


def apply_pacing_revision(values: Mapping[str, object], actor: object = "") -> int | None:
    """Commit an allowlisted policy revision atomically in the current scope."""

    from app.runtime import main as m

    filtered = filter_pacing_updates(values)
    if not filtered:
        return None
    scope_key = _policy_scope_key(m)
    conn = m._scoped_sqlite_conn()
    with conn:
        revision = _apply_pacing_revision_to_connection(
            conn,
            scope_key=scope_key,
            values=filtered,
            actor=actor,
        )
    _update_settings_cache(m, filtered)
    return revision


def _record_policy_apply_result(
    m,
    *,
    desired_revision: int,
    tenant_id: int,
    status: str,
    safe_error: str = "",
) -> None:
    with m._global_conn() as conn:
        conn.execute(
            "INSERT INTO policy_apply_results "
            "(version_id, tenant_id, status, safe_error) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(version_id, tenant_id) DO UPDATE SET "
            "status=excluded.status, safe_error=excluded.safe_error, "
            "applied_at=CURRENT_TIMESTAMP",
            (desired_revision, tenant_id, status, safe_error[:128]),
        )


def propagate_global_pacing_settings(
    values: Mapping[str, object],
    desired_revision: int | None = None,
    actor: object = "",
) -> PacingFanoutReport:
    """Apply one global revision to tenants and record partial failures.

    Each tenant SQLite transaction is independent. The global revision and its
    apply results are durable, but this function never claims a cross-DB
    transaction.
    """
    from app.runtime import main as m
    from app.tenant import tenant_scope

    filtered = filter_pacing_updates(values)
    if not filtered:
        return PacingFanoutReport(
            desired_revision=int(desired_revision or 0), applied=[], failed={}
        )
    if desired_revision is None:
        desired_revision = apply_pacing_revision(filtered, actor=actor)
    if desired_revision is None:
        raise RuntimeError("policy_revision_not_created")

    applied: list[int] = []
    failed: dict[int, str] = {}
    for tid in sorted(iter_tenant_ids(m.ROOT)):
        try:
            with tenant_scope(tenant_id=tid, role="admin"):
                conn = m._conn()
                with conn:
                    _apply_pacing_revision_to_connection(
                        conn,
                        scope_key=f"tenant:{tid}",
                        values=filtered,
                        actor=actor,
                        source_revision=int(desired_revision),
                    )
                _update_settings_cache(m, filtered)
            _record_policy_apply_result(
                m,
                desired_revision=int(desired_revision),
                tenant_id=tid,
                status="applied",
            )
            applied.append(tid)
        except Exception:
            logger.error("pacing settings copy failed tenant_id=%s", tid)
            safe_error = "tenant_apply_failed"
            failed[tid] = safe_error
            _record_policy_apply_result(
                m,
                desired_revision=int(desired_revision),
                tenant_id=tid,
                status="failed",
                safe_error=safe_error,
            )
    return PacingFanoutReport(
        desired_revision=int(desired_revision), applied=applied, failed=failed
    )
