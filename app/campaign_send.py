"""Campaign send path and pacing (phase 2 extraction from main.py)."""

from __future__ import annotations

import asyncio
import random
import sqlite3
import time
from datetime import datetime

import antiban_core

from app.campaign_facade import main


def _setting_float(key: str, default: float) -> float:
    try:
        return float(main.get_setting(key) or str(default))
    except ValueError:
        return default


def _setting_int(key: str, default: int) -> int:
    try:
        return int(float(main.get_setting(key) or str(default)))
    except ValueError:
        return default


def _human_pauses_enabled() -> bool:
    return main._setting_truthy("human_pauses_enabled", "1")


def _jitter_percent_now(now: datetime | None = None) -> float:
    base = _setting_float("jitter_percent", 40.0)
    if not _human_pauses_enabled():
        return max(0.0, min(100.0, base))
    now = now or main._local_now()
    hour = now.hour
    if hour < 13:
        j = _setting_float("jitter_morning_percent", 55.0)
    elif hour >= 16:
        j = _setting_float("jitter_evening_percent", 35.0)
    else:
        j = base
    return max(0.0, min(100.0, j))


def compute_send_delay_sec(*, pool_scale: bool = False) -> tuple[float, str]:
    lo = float(_setting_int("delay_min_sec", 60))
    hi = float(_setting_int("delay_max_sec", 180))
    lo, hi = antiban_core.clamp_range(lo, hi)
    kind = "normal"
    if _human_pauses_enabled():
        short_ch = max(0.0, min(100.0, _setting_float("short_pause_chance", 15.0)))
        long_ch = max(0.0, min(100.0, _setting_float("long_pause_chance", 10.0)))
        roll = random.random() * 100.0
        if long_ch > 0 and roll < long_ch:
            slo = float(_setting_int("long_pause_min_sec", 300))
            shi = float(_setting_int("long_pause_max_sec", 900))
            lo, hi = antiban_core.clamp_range(slo, shi)
            kind = "long"
        elif short_ch > 0 and roll < long_ch + short_ch:
            slo = float(_setting_int("short_pause_min_sec", 30))
            shi = float(_setting_int("short_pause_max_sec", 50))
            lo, hi = antiban_core.clamp_range(slo, shi)
            kind = "short"
    delay = antiban_core.lognormal_delay_sec(
        lo, hi, jitter_percent=_jitter_percent_now()
    )
    _ = pool_scale
    return delay, kind


async def sleep_send_delay(*, pool_scale: bool = False) -> None:
    delay, kind = compute_send_delay_sec(pool_scale=pool_scale)
    if kind == "long":
        main.append_log(f"Длинная пауза («отвлёкся»): ~{int(delay // 60)} мин")
    elif kind == "short":
        main.append_log(f"Короткая пауза: {int(delay)} с")
    end_at = time.monotonic() + delay
    while time.monotonic() < end_at:
        main._touch_worker_activity()
        left = end_at - time.monotonic()
        if left <= 0:
            break
        await asyncio.sleep(min(30.0, left))


async def send_with_retry(
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
    for attempt in range(main.MAX_RETRY):
        main._touch_worker_activity()
        try:
            final_text = main._prepare_outgoing_text(
                text, profile, group, int(group["id"])
            )

            async def _do(c, g=group, t=final_text):
                cid = await main.resolve_chat_id(c, g)
                if not cid:
                    raise RuntimeError("Не удалось определить chat_id")
                chat_id = int(cid)
                await c.get_chat(chat_id)
                await main._human_presence_before_send(c, chat_id)
                await c.send_message(chat_id=chat_id, text=t)
                return cid

            await main._with_client(
                profile["id"],
                profile["phone"],
                _do,
                group_id=int(group["id"]),
            )
            today = main._local_today().isoformat()
            with main._conn() as c:
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
            main._on_success(profile["id"])
            main._note_human_burst(int(profile["id"]))
            main._touch_worker_activity()
            main._metric_inc("messages_sent_total")
            main.append_log(
                f"Успех #{profile['id']} → «{group['name']}»: {final_text[:50]}…"
            )
            return True
        except Exception as e:
            last_err = str(e)
            is_auth_err = main._is_auth_error(last_err)
            if is_auth_err and attempt == 0:
                main.append_log(
                    f"Авто-реавторизация #{profile['id']}: повтор подключения "
                    f"после ошибки сессии…"
                )
                await asyncio.sleep(2)
                main._touch_worker_activity()
                continue
            if is_auth_err or attempt == main.MAX_RETRY - 1:
                if is_auth_err:
                    last_err = (
                        f"{last_err} — требуется повторный вход (кнопка «Войти» / «Заново»)"
                    )
                ban = main._mark_profile_failed(profile["id"], last_err, is_auth_err)
                if ban:
                    await main._handle_profile_banned(profile["id"], last_err)
                with main._conn() as c:
                    c.execute(
                        "INSERT INTO send_log (profile_id, group_id, message_idx, status, error) "
                        "VALUES (?, ?, ?, 'failed', ?)",
                        (profile["id"], group["id"], mi, last_err),
                    )
                main._metric_inc("messages_failed_total")
                main.append_log(f"Ошибка #{profile['id']}: {last_err}")
                return False
            delay = main.RETRY_DELAYS[attempt]
            main.append_log(
                f"Попытка {attempt + 1}/{main.MAX_RETRY} для #{profile['id']}, "
                f"повтор через {delay}с: {last_err}"
            )
            await asyncio.sleep(delay)
            main._touch_worker_activity()
    return False
