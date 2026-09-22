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
from app.repositories.operations import OperationRepository
from app.services.operations import OperationLedger

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
    provider_message_id: str = ""
    operation_id: str = ""
    budget_date: str = ""
    operation_ledger: OperationLedger | None = None

    def mark_in_flight(self) -> None:
        if self.outcome == SEND_NOT_STARTED:
            self.outcome = SEND_IN_FLIGHT
        self.may_requeue = False

    def mark_accepted(self, *, provider_message_id: str) -> None:
        if not provider_message_id.strip():
            raise ValueError("provider_message_id is required")
        self.outcome = SEND_ACCEPTED
        self.may_requeue = False
        self.provider_message_id = provider_message_id

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
    except (ValueError, sqlite3.Error):
        return default


def _setting_int(key: str, default: int) -> int:
    try:
        return int(float(main.get_setting(key) or str(default)))
    except (ValueError, sqlite3.Error):
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
    mandatory_floor = max(5.0, lo)
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
    lo = max(mandatory_floor, lo)
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
    operation_id: str = "",
    budget_date: str = "",
    daily_plan_id: str | None = None,
    slot_id: str | None = None,
) -> None:
    with main._conn() as c:
        send_log_columns = {
            str(row[1]) for row in c.execute("PRAGMA table_info(send_log)").fetchall()
        }
        if "operation_id" in send_log_columns and operation_id:
            existing = c.execute(
                "SELECT id FROM send_log WHERE operation_id=? LIMIT 1",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                return
        if status == "sent":
            today = main._local_today().isoformat()
            if not budget_date or budget_date == today:
                c.execute(
                    "UPDATE profiles SET messages_sent_today=messages_sent_today+1, "
                    "sent_day=?, last_error='', fail_count=0 WHERE id=?",
                    (today, profile["id"]),
                )
            log_columns = [
                "profile_id",
                "group_id",
                "message_idx",
                "status",
                "sent_text",
            ]
            log_values: list[object] = [
                profile["id"],
                group["id"],
                mi,
                "sent",
                sent_text[:2000],
            ]
            for column, value in (
                ("operation_id", operation_id),
                ("daily_plan_id", daily_plan_id),
                ("slot_id", slot_id),
            ):
                if column in send_log_columns and value:
                    log_columns.append(column)
                    log_values.append(value)
            placeholders = ", ".join("?" for _ in log_columns)
            c.execute(
                f"INSERT INTO send_log ({', '.join(log_columns)}) "
                f"VALUES ({placeholders})",
                log_values,
            )
        else:
            log_columns = ["profile_id", "group_id", "message_idx", "status", "error"]
            log_values = [profile["id"], group["id"], mi, status, error[:500]]
            for column, value in (
                ("operation_id", operation_id),
                ("daily_plan_id", daily_plan_id),
                ("slot_id", slot_id),
            ):
                if column in send_log_columns and value:
                    log_columns.append(column)
                    log_values.append(value)
            placeholders = ", ".join("?" for _ in log_columns)
            c.execute(
                f"INSERT INTO send_log ({', '.join(log_columns)}) "
                f"VALUES ({placeholders})",
                log_values,
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


def _operation_scope() -> str:
    if not main._is_server_mode():
        return "local"
    from app.tenant import get_tenant_id

    tenant_id = get_tenant_id()
    if tenant_id is None:
        raise RuntimeError("tenant scope is required for campaign operations")
    return f"tenant:{int(tenant_id)}"


def _start_send_operation(
    *,
    tracker: SendTracker,
    profile: sqlite3.Row,
    group: sqlite3.Row,
    text: str,
    daily_plan_id: str | None = None,
    slot_id: str | None = None,
) -> None:
    """Persist the logical send before any client/gateway callback runs."""
    if tracker.operation_id:
        return
    repository = OperationRepository(main._conn())
    ledger = OperationLedger(repository)
    if slot_id:
        existing = repository.find_retryable_for_slot(
            slot_id, profile_id=int(profile["id"]), text=text
        )
        if existing is not None:
            if existing.group_id != int(group["id"]):
                raise RuntimeError("daily slot route does not match retryable operation")
            if existing.status == "failed_unsent":
                resumed = ledger.retry(
                    existing.operation_id,
                    proof_no_send=True,
                    profile_id=int(profile["id"]),
                )
            else:
                resumed = ledger.claim(existing.operation_id, profile_id=int(profile["id"]))
            tracker.operation_id = resumed.operation_id
            tracker.budget_date = resumed.budget_date or main._local_today().isoformat()
            tracker.operation_ledger = ledger
            return
    budget_date = main._local_today().isoformat()
    operation = ledger.create_operation(
        scope=_operation_scope(),
        profile_id=int(profile["id"]),
        group_id=int(group["id"]),
        text=text,
        budget_date=budget_date,
        daily_plan_id=daily_plan_id,
        slot_id=slot_id,
        route_snapshot={},
        max_pre_effect_retries=max(0, int(main.MAX_RETRY) - 1),
    )
    claimed = ledger.claim(operation.operation_id, profile_id=int(profile["id"]))
    tracker.operation_id = claimed.operation_id
    tracker.budget_date = budget_date
    tracker.operation_ledger = ledger


def _mark_operation_failed_unsent(tracker: SendTracker, error: str) -> None:
    if tracker.operation_ledger is None or not tracker.operation_id:
        return
    try:
        tracker.operation_ledger.mark_failed_unsent(tracker.operation_id, error)
    except Exception:
        # The external call is still prohibited until in_flight is committed;
        # recovery can reconcile a partially persisted operation later.
        pass


def _mark_operation_unknown(tracker: SendTracker, error: str) -> None:
    if tracker.operation_ledger is None or not tracker.operation_id:
        return
    try:
        tracker.operation_ledger.mark_unknown(tracker.operation_id, error)
    except Exception:
        # Keep the in-memory no-retry decision even if the local DB is down.
        pass


def _retry_send_operation(tracker: SendTracker, *, profile_id: int) -> None:
    if tracker.operation_ledger is None or not tracker.operation_id:
        return
    tracker.operation_ledger.retry(
        tracker.operation_id,
        proof_no_send=True,
        profile_id=profile_id,
    )


def recover_inflight_operations() -> list[str]:
    """Fail closed after a process restart; never contact MAX during recovery."""
    ledger = OperationLedger(OperationRepository(main._conn()))
    return ledger.recover()


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
    daily_plan_id: str | None = None,
    slot_id: str | None = None,
) -> bool:
    """Отправка с retry. True = успех, False = окончательный провал.

    Requeue is allowed only when tracker.may_requeue is True (send never started).
    """
    state = tracker if tracker is not None else SendTracker()
    last_err = ""
    try:
        final_text = (
            text
            if slot_id
            else main._prepare_outgoing_text(text, profile, group, int(group["id"]))
        )
        _start_send_operation(
            tracker=state,
            profile=profile,
            group=group,
            text=final_text,
            daily_plan_id=daily_plan_id,
            slot_id=slot_id,
        )
    except Exception as exc:
        state.mark_failed_unsent(str(exc))
        main.append_log(
            f"Операция отправки не зарезервирована #{profile['id']}: {exc}"
        )
        return False
    persist_kw = dict(
        profile=profile,
        group=group,
        mi=mi,
        pi=pi,
        gi_next=gi_next,
        mi_next=mi_next,
        sent_text=final_text,
        advance_queue=advance_queue,
        operation_id=state.operation_id,
        budget_date=state.budget_date,
        daily_plan_id=daily_plan_id,
        slot_id=slot_id,
    )
    for attempt in range(main.MAX_RETRY):
        main._touch_worker_activity()
        try:
            if attempt > 0:
                _retry_send_operation(state, profile_id=int(profile["id"]))

            async def _do(c, g=group, t=final_text, tr=state):
                gateway = main._max_gateway(c)
                cid = await main.resolve_chat_id(gateway, g)
                chat_id = int(cid)
                await gateway.check_destination(chat_id=chat_id)
                if tr.operation_ledger is not None:
                    tr.operation_ledger.mark_in_flight(
                        tr.operation_id,
                        route_snapshot={
                            "group_id": int(g["id"]),
                            "chat_id": str(cid),
                        },
                    )
                tr.mark_in_flight()
                ack = await gateway.send_message(chat_id=chat_id, text=t)
                if tr.operation_ledger is not None:
                    tr.operation_ledger.mark_accepted(
                        tr.operation_id,
                        provider_message_id=ack.message_id,
                    )
                tr.mark_accepted(provider_message_id=ack.message_id)
                return cid

            await main._with_client(
                profile["id"],
                profile["phone"],
                _do,
                group_id=int(group["id"]),
            )
            if state.outcome == SEND_IN_FLIGHT:
                state.mark_unknown("client returned without send acknowledgement")
                _mark_operation_unknown(state, state.error)
                _persist_send_outcome(status="unknown", error=state.error, **persist_kw)
                return False
            if state.outcome != SEND_ACCEPTED:
                raise RuntimeError("client returned without provider acknowledgement")
            housekeeping_errors: list[str] = []
            if state.operation_ledger is not None:
                housekeeping_errors = state.operation_ledger.finalize_accepted(
                    state.operation_id,
                    provider_message_id=state.provider_message_id,
                    post_commit_hooks=[
                        lambda: _persist_send_outcome(status="sent", **persist_kw)
                    ],
                )
            else:
                _persist_send_outcome(status="sent", **persist_kw)
            if housekeeping_errors:
                state.terminal_status = "accepted_accounting_pending"
                try:
                    main.append_log(
                        f"ACK сохранён, но локальный учёт отложен #{profile['id']}: "
                        + "; ".join(housekeeping_errors)
                    )
                except Exception:
                    pass
            try:
                main._on_success(profile["id"])
                main._note_human_burst(int(profile["id"]))
                main._touch_worker_activity()
                main._metric_inc("messages_sent_total")
                main.append_log(
                    f"Успех #{profile['id']} → «{group['name']}»: {final_text[:50]}…"
                )
            except Exception as exc:
                state.terminal_status = "accepted_housekeeping_pending"
                try:
                    main.append_log(
                        f"ACK сохранён, но post-ACK учёт требует восстановления "
                        f"#{profile['id']}: {exc}"
                    )
                except Exception:
                    pass
            return True
        except asyncio.CancelledError:
            policy = classify_send_exception(asyncio.CancelledError(), state.outcome)
            if policy == SAFE_TO_RETRY:
                _mark_operation_failed_unsent(state, "cancelled before send")
                state.may_requeue = True
                raise
            _mark_operation_unknown(state, "cancelled after send started")
            _persist_interrupt(state, **persist_kw)
            raise
        except Exception as e:
            last_err = str(e)
            policy = classify_send_exception(e, state.outcome)
            if policy != SAFE_TO_RETRY:
                state.mark_unknown(last_err)
                _mark_operation_unknown(state, last_err)
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
            _mark_operation_failed_unsent(state, last_err)
            parsed = antiban_core.flood_wait_seconds(last_err)
            if parsed is not None:
                main._persist_server_retry_after(profile["id"], parsed)
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
                if parsed is not None:
                    main._persist_server_retry_after(profile["id"], parsed)
                state.mark_failed_unsent(last_err)
                try:
                    _persist_send_outcome(status="failed", error=last_err, **persist_kw)
                except Exception:
                    pass
                main._metric_inc("messages_failed_total")
                main.append_log(f"Ошибка #{profile['id']}: {last_err}")
                return False
            delay = main.RETRY_DELAYS[attempt]
            if parsed is not None:
                delay = max(delay, parsed)
            main.append_log(
                f"Попытка {attempt + 1}/{main.MAX_RETRY} для #{profile['id']}, "
                f"повтор через {delay}с: {last_err}"
            )
            remaining = float(delay)
            while remaining > 0:
                main._touch_worker_activity()
                chunk = min(30.0, remaining)
                await asyncio.sleep(chunk)
                remaining -= chunk
    state.mark_failed_unsent(last_err)
    return False
