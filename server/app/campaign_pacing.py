"""Circuit breaker + human burst/break pacing (in-memory, per profile)."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from datetime import datetime, timedelta

import antiban_core
from app.campaign_runtime import RUNTIME

PersistFn = Callable[[int], None]
LogFn = Callable[[str], None]
SettingFloatFn = Callable[[str, float], float]
SettingIntFn = Callable[[str, int], int]
LocalNowFn = Callable[[], datetime]
TruthFn = Callable[[], bool]


def on_success(profile_id: int, persist: PersistFn) -> None:
    RUNTIME.consecutive_errors.pop(profile_id, None)
    RUNTIME.circuit_opened_at.pop(profile_id, None)
    persist(profile_id)


def on_error(
    profile_id: int,
    *,
    persist: PersistFn,
    log: LogFn,
    setting_float: SettingFloatFn,
    max_consecutive_errors: int,
    default_circuit_minutes: float,
) -> None:
    n = RUNTIME.consecutive_errors.get(profile_id, 0) + 1
    RUNTIME.consecutive_errors[profile_id] = n
    mins = max(1.0, setting_float("circuit_break_minutes", default_circuit_minutes))
    if n >= max_consecutive_errors:
        RUNTIME.circuit_opened_at.setdefault(profile_id, time.time())
        log(
            f"Автопауза: профиль #{profile_id} отключён на "
            f"{int(mins)} мин после {n} ошибок подряд"
        )
    persist(profile_id)


def is_circuit_open(
    profile_id: int,
    *,
    persist: PersistFn,
    log: LogFn,
    setting_float: SettingFloatFn,
    max_consecutive_errors: int,
    default_circuit_minutes: float,
) -> bool:
    count = RUNTIME.consecutive_errors.get(profile_id, 0)
    if count < max_consecutive_errors:
        return False
    opened = RUNTIME.circuit_opened_at.get(profile_id, 0.0)
    mins = max(1.0, setting_float("circuit_break_minutes", default_circuit_minutes))
    if time.time() - opened > mins * 60:
        on_success(profile_id, persist)
        log(f"Автопауза: профиль #{profile_id} снова доступен")
        return False
    return True


def circuit_open_count(
    *,
    persist: PersistFn,
    log: LogFn,
    setting_float: SettingFloatFn,
    max_consecutive_errors: int,
    default_circuit_minutes: float,
) -> int:
    return sum(
        1
        for pid in list(RUNTIME.consecutive_errors)
        if is_circuit_open(
            pid,
            persist=persist,
            log=log,
            setting_float=setting_float,
            max_consecutive_errors=max_consecutive_errors,
            default_circuit_minutes=default_circuit_minutes,
        )
    )


def is_in_human_break(profile_id: int, *, local_now: LocalNowFn, persist: PersistFn) -> bool:
    until = RUNTIME.human_break_until.get(profile_id)
    if not until:
        return False
    if local_now() >= until:
        RUNTIME.human_break_until.pop(profile_id, None)
        persist(profile_id)
        return False
    return True


def note_human_burst(
    profile_id: int,
    *,
    enabled: TruthFn,
    setting_int: SettingIntFn,
    local_now: LocalNowFn,
    persist: PersistFn,
    log: LogFn,
) -> None:
    if not enabled():
        return
    n = setting_int("break_after_n", 4)
    if n <= 0:
        return
    burst = RUNTIME.human_burst_count.get(profile_id, 0) + 1
    if burst < n:
        RUNTIME.human_burst_count[profile_id] = burst
        persist(profile_id)
        return
    RUNTIME.human_burst_count[profile_id] = 0
    blo, bhi = antiban_core.clamp_range(
        float(setting_int("break_min_sec", 1200)),
        float(setting_int("break_max_sec", 2400)),
    )
    secs = random.uniform(blo, bhi)
    until = local_now() + timedelta(seconds=secs)
    RUNTIME.human_break_until[profile_id] = until
    persist(profile_id)
    log(
        f"Перерыв аккаунта #{profile_id} после {n} сообщений: "
        f"~{int(secs // 60)} мин (до {until.strftime('%H:%M')})"
    )


def seconds_until_any_human_break_ends(*, local_now: LocalNowFn) -> float:
    now = local_now()
    waits = [
        (until - now).total_seconds()
        for until in RUNTIME.human_break_until.values()
        if until > now
    ]
    return max(1.0, min(waits)) if waits else 30.0


def load_antiban_row(
    profile_id: int,
    *,
    burst_count: int,
    break_until_raw: str | None,
    consecutive_errors: int,
    circuit_opened_at: float | None,
    local_now: LocalNowFn,
    setting_float: SettingFloatFn,
    max_consecutive_errors: int,
    default_circuit_minutes: float,
) -> None:
    now = local_now()
    wall = time.time()
    if burst_count > 0:
        RUNTIME.human_burst_count[profile_id] = burst_count
    if break_until_raw:
        try:
            until = datetime.fromisoformat(str(break_until_raw))
            if until.tzinfo is not None:
                until = until.replace(tzinfo=None)
            if until > now:
                RUNTIME.human_break_until[profile_id] = until
        except ValueError:
            pass
    if consecutive_errors > 0:
        RUNTIME.consecutive_errors[profile_id] = consecutive_errors
    if circuit_opened_at is not None and consecutive_errors >= max_consecutive_errors:
        mins = max(1.0, setting_float("circuit_break_minutes", default_circuit_minutes))
        if wall - float(circuit_opened_at) < mins * 60:
            RUNTIME.circuit_opened_at[profile_id] = float(circuit_opened_at)
        else:
            RUNTIME.consecutive_errors.pop(profile_id, None)


def antiban_snapshot(profile_id: int) -> tuple[int, datetime | None, int, float | None]:
    return (
        RUNTIME.human_burst_count.get(profile_id, 0),
        RUNTIME.human_break_until.get(profile_id),
        RUNTIME.consecutive_errors.get(profile_id, 0),
        RUNTIME.circuit_opened_at.get(profile_id),
    )
