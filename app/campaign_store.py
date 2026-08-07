"""Campaign rows in SQLite (begin/finish/config snapshot)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable

from app.campaign_runtime import RUNTIME

GetSetting = Callable[[str], str | None]
LogFn = Callable[[str], None]


def config_snapshot(*, get_setting: GetSetting, messages_total: int) -> str:
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
            "role_active_percent": get_setting("role_active_percent"),
            "role_quiet_percent": get_setting("role_quiet_percent"),
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
            "messages_total": messages_total,
        },
        ensure_ascii=False,
    )


def begin(
    conn: sqlite3.Connection,
    *,
    messages_total: int,
    config_json: str,
    scheduled_for: str | None = None,
    log: LogFn | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO campaigns (started_at, status, messages_total, scheduled_for, config_json) "
        "VALUES (datetime('now'), 'running', ?, ?, ?)",
        (messages_total, scheduled_for, config_json),
    )
    cid = int(cur.lastrowid)
    RUNTIME.current_campaign_id = cid
    if log:
        log(f"Кампания #{cid} запущена ({messages_total} сообщений)")
    return cid


def find_running_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT id FROM campaigns WHERE status='running' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return int(row["id"]) if row else None


def finish(
    conn: sqlite3.Connection,
    *,
    campaign_id: int | None,
    status: str,
    reason: str = "",
) -> None:
    cid = campaign_id or find_running_id(conn)
    if not cid:
        return
    sent = conn.execute(
        "SELECT COUNT(*) n FROM send_log WHERE status='sent' AND sent_at >= "
        "(SELECT started_at FROM campaigns WHERE id=?)",
        (cid,),
    ).fetchone()["n"]
    failed = conn.execute(
        "SELECT COUNT(*) n FROM send_log WHERE status='failed' AND sent_at >= "
        "(SELECT started_at FROM campaigns WHERE id=?)",
        (cid,),
    ).fetchone()["n"]
    conn.execute(
        "UPDATE campaigns SET finished_at=datetime('now'), status=?, "
        "messages_sent=?, messages_failed=?, reason=? WHERE id=?",
        (status, sent, failed, reason[:500], cid),
    )
    RUNTIME.current_campaign_id = None


def has_running(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute("SELECT 1 FROM campaigns WHERE status='running' LIMIT 1").fetchone()
        is not None
    )
