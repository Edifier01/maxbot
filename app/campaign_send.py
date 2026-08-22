"""Campaign send path and pacing (phase 2 extraction from main.py)."""

from __future__ import annotations

import asyncio
import random
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime

import antiban_core

from app.campaign_facade import main

SEND_NOT_STARTED = "not_started"
SEND_IN_FLIGHT = "in_flight"
SEND_ACCEPTED = "accepted"
SEND_FAILED = "failed"
SEND_UNKNOWN = "unknown"

SAFE_TO_RETRY = "safe_to_retry"
UNSAFE_TO_RETRY = "unsafe_to_retry"
RETRY_UNKNOWN = "unknown"

_UNSAFE_NETWORK_MARKERS = (
    "timeout",
    "timed out",
    "connection reset",
    "connection aborted",
    "connectionerror",
    "broken pipe",
    "server disconnected",
    "network is unreachable",
    "temporarily unavailable",
    "winerror 10054",
    "winerror 10053",
    "winerror 10060",
)


@dataclass
class SendTracker:
    """Mutable send lifecycle. Survives CancelledError (await never returns)."""

    outcome: str = SEND_NOT_STARTED
    may_requeue: bool = True
    terminal_status: str = ""
    error: str = ""

    def mark_in_flight(self) -> None:
        if self.outcome == SEND_NOT_STARTED:
            self.outcome = SEND_IN_FLIGHT
        self.may_requeue = False

    def mark_accepted(self) -> None:
        self.outcome = SEND_ACCEPTED
        self.may_requeue = False

    def mark_unknown(self, error: str = "") -> None:
        if self.outcome != SEND_ACCEPTED:
            self.outcome = SEND_UNKNOWN
        self.may_requeue = False
        if error:
            self.error = error[:500]

    def mark_failed_unsent(self, error: str = "") -> None:
        if self.outcome in (SEND_NOT_STARTED, SEND_FAILED):
            self.outcome = SEND_FAILED
            self.may_requeue = True
        if error:
            self.error = error[:500]


def classify_send_exception(exc: BaseException, outcome: str) -> str:
    """SAFE_TO_RETRY only when the MAX send definitely did not happen."""
    if isinstance(exc, asyncio.CancelledError):
        if outcome == SEND_NOT_STARTED:
            return SAFE_TO_RETRY
        if outcome == SEND_ACCEPTED:
            return UNSAFE_TO_RETRY
        return RETRY_UNKNOWN
    err = str(exc)
    if antiban_core.flood_wait_seconds(err) is not None:
        return SAFE_TO_RETRY
    if outcome in (SEND_IN_FLIGHT, SEND_ACCEPTED, SEND_UNKNOWN):
        return RETRY_UNKNOWN
    return SAFE_TO_RETRY


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
    lo = max(5.0, lo)
    hi = max(lo, hi)
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


def _persist_send_outcome(
    *,
    profile: sqlite3.Row,
    group: sqlite3.Row,
    mi: int,
    pi: int,
    gi_next: int,
    mi_next: int,
    status: str,
    sent_text: str = "",
    error: str = "",
    advance_queue: bool = True,
) -> None:
    with main._conn() as c:
        if status == "sent":
            today = main._local_today().isoformat()
            c.execute(
                "UPDATE profiles SET messages_sent_today=messages_sent_today+1, "
                "sent_day=?, last_error='', fail_count=0 WHERE id=?",
                (today, profile["id"]),
            )
            c.execute(
                "INSERT INTO send_log (profile_id, group_id, message_idx, status, sent_text) "
                "VALUES (?, ?, ?, 'sent', ?)",
                (profile["id"], group["id"], mi, sent_text[:2000]),
            )
        else:
            c.execute(
                "INSERT INTO send_log (profile_id, group_id, message_idx, status, error) "
                "VALUES (?, ?, ?, ?, ?)",
                (profile["id"], group["id"], mi, status, error[:500]),
            )
        if advance_queue:
            c.execute(
                "UPDATE queue_state SET profile_idx=?, message_idx=?, group_idx=? WHERE id=1",
                (pi, mi_next, gi_next),
            )
        elif status in ("sent", "unknown"):
            c.execute(
                "UPDATE queue_state SET profile_idx=?, group_idx=? WHERE id=1",
                (pi, gi_next),
            )


def _persist_interrupt(tracker: SendTracker, **kwargs) -> None:
    """Best-effort SQLite ack after MAX may already have the message. Never raises."""
    try:
        if tracker.outcome == SEND_ACCEPTED:
            _persist_send_outcome(status="sent", **kwargs)
            tracker.terminal_status = "sent"
        else:
            tracker.mark_unknown(tracker.error or "interrupted")
            _persist_send_outcome(
                status="unknown",
                error=tracker.error or "interrupted after send started",
                **kwargs,
            )
            tracker.terminal_status = "unknown"
        tracker.may_requeue = False
    except Exception:
        tracker.may_requeue = False


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
    tracker: SendTracker | None = None,
) -> bool:
    """Отправка с retry. True = успех, False = окончательный провал.

    Requeue is allowed only when tracker.may_requeue is True (send never started).
    """
    state = tracker if tracker is not None else SendTracker()
    last_err = ""
    final_text = text
    persist_kw = dict(
        profile=profile,
        group=group,
        mi=mi,
        pi=pi,
        gi_next=gi_next,
        mi_next=mi_next,
        sent_text="",
        advance_queue=advance_queue,
    )
    for attempt in range(main.MAX_RETRY):
        main._touch_worker_activity()
        try:
            final_text = main._prepare_outgoing_text(
                text, profile, group, int(group["id"])
            )
            persist_kw["sent_text"] = final_text

            async def _do(c, g=group, t=final_text, tr=state):
                cid = await main.resolve_chat_id(c, g)
                if not cid:
                    raise RuntimeError("Не удалось определить chat_id")
                chat_id = int(cid)
                await c.get_chat(chat_id)
                await main._human_presence_before_send(c, chat_id)
                tr.mark_in_flight()
                await c.send_message(chat_id=chat_id, text=t)
                tr.mark_accepted()
                return cid

            await main._with_client(
                profile["id"],
                profile["phone"],
                _do,
                group_id=int(group["id"]),
            )
            if state.outcome == SEND_IN_FLIGHT:
                state.mark_unknown("client returned without send acknowledgement")
                _persist_send_outcome(status="unknown", error=state.error, **persist_kw)
                return False
            if state.outcome != SEND_ACCEPTED:
                state.mark_accepted()
            _persist_send_outcome(status="sent", **persist_kw)
            main._on_success(profile["id"])
            main._note_human_burst(int(profile["id"]))
            main._touch_worker_activity()
            main._metric_inc("messages_sent_total")
            main.append_log(
                f"Успех #{profile['id']} → «{group['name']}»: {final_text[:50]}…"
            )
            return True
        except asyncio.CancelledError:
            policy = classify_send_exception(asyncio.CancelledError(), state.outcome)
            if policy == SAFE_TO_RETRY:
                state.may_requeue = True
                raise
            _persist_interrupt(state, **persist_kw)
            raise
        except Exception as e:
            last_err = str(e)
            policy = classify_send_exception(e, state.outcome)
            if policy != SAFE_TO_RETRY:
                state.mark_unknown(last_err)
                try:
                    _persist_send_outcome(
                        status="unknown", error=last_err, **persist_kw
                    )
                except Exception:
                    pass
                main.append_log(
                    f"Исход отправки неизвестен #{profile['id']}: {last_err}"
                )
                return False
            state.outcome = SEND_NOT_STARTED
            state.may_requeue = True
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
                state.mark_failed_unsent(last_err)
                try:
                    _persist_send_outcome(status="failed", error=last_err, **persist_kw)
                except Exception:
                    pass
                main._metric_inc("messages_failed_total")
                main.append_log(f"Ошибка #{profile['id']}: {last_err}")
                return False
            delay = main.RETRY_DELAYS[attempt]
            parsed = antiban_core.flood_wait_seconds(last_err)
            if parsed is not None:
                delay = max(delay, parsed)
            main.append_log(
                f"Попытка {attempt + 1}/{main.MAX_RETRY} для #{profile['id']}, "
                f"повтор через {delay}с: {last_err}"
            )
            end_at = time.monotonic() + float(delay)
            while time.monotonic() < end_at:
                main._touch_worker_activity()
                left = end_at - time.monotonic()
                if left <= 0:
                    break
                await asyncio.sleep(min(30.0, left))
    state.mark_failed_unsent(last_err)
    return False
