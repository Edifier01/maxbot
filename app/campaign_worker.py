"""Campaign worker orchestration (extracted from main.py)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import random
import time
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen

from fastapi import HTTPException

from app.runtime import main
from app.campaign_runtime import REGISTRY, RUNTIME
from app.campaign_send import send_with_retry, sleep_send_delay


def worker_shutdown(reason: str) -> None:
    main.append_log(reason)
    with main._conn() as c:
        c.execute("UPDATE queue_state SET running=0 WHERE id=1")
    main.append_log("Воркер остановлен")
    status = "completed" if reason.startswith("Готово") else "stopped"
    finish_campaign(status, reason)
    # уведомления в фоне
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(notify_campaign_end(status, reason))
    except RuntimeError:
        pass


def campaign_config_snapshot() -> str:
    return json.dumps(
        {
            "delay_min_sec": main.get_setting("delay_min_sec"),
            "delay_max_sec": main.get_setting("delay_max_sec"),
            "daily_limit_min": main.get_setting("daily_limit_min"),
            "daily_limit_max": main.get_setting("daily_limit_max"),
            "jitter_percent": main.get_setting("jitter_percent"),
            "message_pick_mode": main.get_setting("message_pick_mode"),
            "campaign_goal": main.get_setting("campaign_goal"),
            "worker_pool_size": main.get_setting("worker_pool_size"),
            "human_rhythm_enabled": main.get_setting("human_rhythm_enabled"),
            "send_windows_weekday": main.get_setting("send_windows_weekday"),
            "send_windows_weekend": main.get_setting("send_windows_weekend"),
            "day_skip_percent": main.get_setting("day_skip_percent"),
            "role_plan_enabled": main.get_setting("role_plan_enabled"),
            "role_active_percent": main.get_setting("role_active_percent"),
            "role_quiet_percent": main.get_setting("role_quiet_percent"),
            "role_active_min": main.get_setting("role_active_min"),
            "role_active_max": main.get_setting("role_active_max"),
            "role_quiet_limit": main.get_setting("role_quiet_limit"),
            "human_pauses_enabled": main.get_setting("human_pauses_enabled"),
            "break_after_n": main.get_setting("break_after_n"),
            "warmup_start_min": main.get_setting("warmup_start_min"),
            "warmup_start_max": main.get_setting("warmup_start_max"),
            "lazy_day_percent": main.get_setting("lazy_day_percent"),
            "human_presence_enabled": main.get_setting("human_presence_enabled"),
            "human_texts_enabled": main.get_setting("human_texts_enabled"),
            "text_dedupe_enabled": main.get_setting("text_dedupe_enabled"),
            "messages_total": len(main.load_message_pool()),
        },
        ensure_ascii=False,
    )


def begin_campaign(*, scheduled_for: str | None = None) -> int:
    main._ensure_role_cycle_anchor()
    total = len(main.load_message_pool())
    with main._conn() as c:
        cur = c.execute(
            "INSERT INTO campaigns (started_at, status, messages_total, scheduled_for, config_json) "
            "VALUES (datetime('now'), 'running', ?, ?, ?)",
            (total, scheduled_for, campaign_config_snapshot()),
        )
        RUNTIME.current_campaign_id = int(cur.lastrowid)
    main.append_log(f"Кампания #{RUNTIME.current_campaign_id} запущена ({total} сообщений)")
    return RUNTIME.current_campaign_id or 0


def finish_campaign(status: str, reason: str = "") -> None:
    cid = RUNTIME.current_campaign_id
    if not cid:
        # найти последнюю running
        with main._conn() as c:
            row = c.execute(
                "SELECT id FROM campaigns WHERE status='running' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            cid = row["id"] if row else None
    if not cid:
        return
    with main._conn() as c:
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
    RUNTIME.current_campaign_id = None


def http_post_json(url: str, payload: dict[str, Any], timeout: float = 15) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "MAX-Sender/1.4"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        resp.read()


def telegram_credentials() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat:
        return token, chat
    if not main._is_server_mode():
        return (
            main.get_setting("telegram_bot_token").strip(),
            main.get_setting("telegram_chat_id").strip(),
        )
    return "", ""


def alert_institution_label() -> str:
    if main._is_server_mode():
        try:
            from app import db_pg
            from app.tenant import get_tenant_id

            tid = get_tenant_id()
            if tid:
                tenant = db_pg.get_tenant(tid)
                if tenant:
                    return f"{tenant['institution_name']} (#{tid})"
        except Exception:
            pass
    return "локально"


def schedule_telegram(
    title: str,
    lines: list[str],
    *,
    dedupe_key: str | None = None,
) -> None:
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(telegram_notify(title, lines, dedupe_key=dedupe_key))
    except RuntimeError:
        pass


async def telegram_notify(
    title: str,
    lines: list[str],
    *,
    dedupe_key: str | None = None,
) -> None:
    token, chat_id = telegram_credentials()
    if not token or not chat_id:
        return
    if dedupe_key:
        now = time.time()
        if now - main._tg_notify_at.get(dedupe_key, 0.0) < main._TG_DEDUPE_SEC:
            return
        main._tg_notify_at[dedupe_key] = now
    text = (
        f"MAX Sender · {title}\n"
        f"Учреждение: {alert_institution_label()}\n"
        + "\n".join(lines)
    )
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        await asyncio.to_thread(
            http_post_json, url, {"chat_id": chat_id, "text": text[:4000]}
        )
    except Exception as e:
        main.append_log(f"Telegram ошибка: {e}")


async def notify_campaign_end(status: str, reason: str) -> None:
    payload = {
        "event": "campaign_finished",
        "status": status,
        "reason": reason,
        "version": main.APP_VERSION,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    with main._conn() as c:
        row = c.execute(
            "SELECT * FROM campaigns ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row:
        payload["campaign"] = dict(row)

    webhook = main.get_setting("webhook_url").strip()
    if webhook:
        try:
            await asyncio.to_thread(http_post_json, webhook, payload)
            main.append_log("Вебхук: уведомление отправлено")
        except Exception as e:
            main.append_log(f"Ошибка вебхука: {e}")

    _status_ru = {
        "completed": "завершена",
        "stopped": "остановлена",
        "paused": "на паузе",
        "running": "идёт",
        "failed": "с ошибкой",
    }.get(str(status), str(status))
    campaign = payload.get("campaign") or {}
    await telegram_notify(
        "кампания завершена",
        [
            f"Статус: {_status_ru}",
            reason,
            f"отправлено={campaign.get('messages_sent', '?')} "
            f"ошибок={campaign.get('messages_failed', '?')}",
        ],
    )

def _claim_next_job_sync() -> dict[str, Any] | str | None:
    """Синхронное тело claim_next_job (SQLite под asyncio.to_thread)."""
    with main._conn() as c:
        qs = c.execute("SELECT * FROM queue_state WHERE id=1").fetchone()
        if not qs or not qs["running"]:
            return "STOP"
        main._reset_daily_counts(c)

    messages = main.load_message_pool()
    groups = main._active_groups()
    if not messages or not groups:
        return None

    with main._conn() as c:
        qs = c.execute("SELECT * FROM queue_state WHERE id=1").fetchone()
        if not qs or not qs["running"]:
            return "STOP"
        pi, mi, gi = qs["profile_idx"], qs["message_idx"], qs["group_idx"]

        if main._campaign_goal() == "message_pool":
            if main._message_pick_mode() == "random_norepeat":
                bag = main._ensure_message_bag(c, len(messages))
                if not bag:
                    if not RUNTIME.pool_done_announced:
                        RUNTIME.pool_done_announced = True
                        return "DONE"
                    return "STOP"
            elif mi >= len(messages):
                if not RUNTIME.pool_done_announced:
                    RUNTIME.pool_done_announced = True
                    return "DONE"
                return "STOP"

        group = groups[gi % len(groups)]
        profiles = main._active_profiles_for_group(group["id"])
        if not profiles:
            if not main._has_active_profiles():
                if not RUNTIME.pool_done_announced:
                    RUNTIME.pool_done_announced = True
                    return "NO_PROFILES"
                return "STOP"
            c.execute(
                "UPDATE queue_state SET group_idx=? WHERE id=1",
                (main.next_index(gi, len(groups)),),
            )
            return None

        profile = None
        attempts = 0
        while attempts < len(profiles):
            cand = profiles[pi % len(profiles)]
            pi = main.next_index(pi, len(profiles))
            attempts += 1
            if main._is_circuit_open(cand["id"]):
                continue
            if not main._can_send_in_group(cand, group["id"]):
                continue
            profile = cand
            break

        if profile is None:
            c.execute(
                "UPDATE queue_state SET profile_idx=?, group_idx=? WHERE id=1",
                (pi, main.next_index(gi, len(groups))),
            )
            return None

        picked = main._pick_next_message(c, messages, mi)
        if picked is None:
            if not RUNTIME.pool_done_announced:
                RUNTIME.pool_done_announced = True
                return "DONE"
            return "STOP"

        text, pool_idx, progress_next, bag_mode = picked
        gi_next = main.next_index(gi, len(groups))
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


async def claim_next_job() -> dict[str, Any] | str | None:
    """Атомарно взять следующее сообщение для пула.

    Returns:
      dict — задача
      \"DONE\" — очередь исчерпана (первый воркер должен завершить кампанию)
      \"STOP\" — running=0 или уже объявлен DONE
      None — временно нечего делать (нет профилей и т.п.)
    """
    async with main._claim_lock:
        return await asyncio.to_thread(_claim_next_job_sync)


async def poolworker_loop(worker_id: int) -> None:
    main.append_log(f"Воркер пула #{worker_id} стартовал")
    # Расфазировка: не ускоряем паузы, а разводим воркеры по времени
    n = main._pool_size()
    if n > 1 and worker_id > 1:
        base = float(main._setting_int("delay_min_sec", 60))
        phase = random.uniform(0.0, max(5.0, base * 0.6))
        stagger = phase * ((worker_id - 1) / max(1, n - 1))
        end_at = time.monotonic() + stagger
        while time.monotonic() < end_at:
            main._touch_worker_activity()
            await asyncio.sleep(min(5.0, end_at - time.monotonic()))
    main._touch_worker_activity()
    while True:
        main._touch_worker_activity()
        if await main._wait_if_outside_send_window():
            continue
        await main._maybe_idle_presence()
        job = await claim_next_job()
        if job == "STOP":
            main.append_log(f"Воркер пула #{worker_id} остановлен")
            return
        if job == "DONE":
            if main._campaign_goal() == "daily_limits":
                worker_shutdown(
                    "Готово: дневные лимиты всех аккаунтов исчерпаны"
                )
            else:
                worker_shutdown("Готово: все сообщения отправлены (pool)")
            return
        if job == "NO_PROFILES":
            worker_shutdown("Нет активных профилей ни в одной группе")
            return
        if job is None:
            if not main._has_sendable_profile():
                if main._has_sendable_profile(ignore_human_break=True):
                    wait = min(60.0, main._seconds_until_any_human_break_ends())
                    end_at = time.monotonic() + wait
                    while time.monotonic() < end_at:
                        main._touch_worker_activity()
                        await asyncio.sleep(min(15.0, end_at - time.monotonic()))
                    continue
                worker_shutdown(
                    "Готово: дневные лимиты всех аккаунтов исчерпаны"
                    if main._campaign_goal() == "daily_limits"
                    else "Некому отправлять: нет активных профилей или дневной лимит исчерпан"
                )
                return
            await asyncio.sleep(2)
            continue

        sent = await send_with_retry(
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
            main._return_to_message_bag(job["mi"])
            await asyncio.sleep(3)
            main._touch_worker_activity()
            continue
        await sleep_send_delay(pool_scale=True)


async def worker_loop() -> None:
    main.append_log("Воркер запущен")
    main._touch_worker_activity()
    while True:
        main._touch_worker_activity()
        if await main._wait_if_outside_send_window():
            continue
        await main._maybe_idle_presence()
        with main._conn() as c:
            qs = c.execute("SELECT * FROM queue_state WHERE id=1").fetchone()
            if not qs or not qs["running"]:
                main.append_log("Воркер остановлен")
                return
            main._reset_daily_counts(c)

        messages = main.load_message_pool()
        groups = main._active_groups()
        if not messages:
            main.append_log("Нет сообщений — загрузите файл сообщений (.txt)")
            await asyncio.sleep(5)
            continue
        if not groups:
            main.append_log("Нет активных групп")
            await asyncio.sleep(5)
            continue

        with main._conn() as c:
            qs = c.execute("SELECT * FROM queue_state WHERE id=1").fetchone()
            pi, mi, gi = qs["profile_idx"], qs["message_idx"], qs["group_idx"]
            if main._campaign_goal() == "message_pool":
                if main._message_pick_mode() == "random_norepeat":
                    bag = main._ensure_message_bag(c, len(messages))
                    if not bag:
                        worker_shutdown(
                            f"Готово: все {len(messages)} сообщений отправлены"
                        )
                        return
                elif mi >= len(messages):
                    worker_shutdown(
                        f"Готово: все {len(messages)} сообщений отправлены"
                    )
                    return

        group = groups[gi % len(groups)]
        profiles = main._active_profiles_for_group(group["id"])
        if not profiles:
            if not main._has_active_profiles():
                worker_shutdown("Нет активных профилей ни в одной группе")
                return
            main.append_log(
                f"Группа «{group['name']}»: сегодня некого слать "
                f"(роли/skip), следующая"
            )
            with main._conn() as c:
                c.execute(
                    "UPDATE queue_state SET group_idx=? WHERE id=1",
                    (main.next_index(gi, len(groups)),),
                )
            await asyncio.sleep(2)
            continue

        # ponytail: linear scan for next sendable profile (O(n) per step; fine for 1000)
        sent = False
        attempts = 0
        while attempts < len(profiles) and not sent:
            profile = profiles[pi % len(profiles)]
            pi = main.next_index(pi, len(profiles))
            attempts += 1
            if main._is_circuit_open(profile["id"]):
                continue
            if not main._can_send_in_group(profile, group["id"]):
                continue

            with main._conn() as c:
                picked = main._pick_next_message(c, messages, mi)
            if picked is None:
                worker_shutdown(
                    f"Готово: все {len(messages)} сообщений отправлены"
                )
                return
            text, pool_idx, progress_next, bag_mode = picked
            gi_next = main.next_index(gi, len(groups))
            sent = await send_with_retry(
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
                main._return_to_message_bag(pool_idx)
            mi = progress_next

        if sent:
            await sleep_send_delay(pool_scale=False)
        else:
            if not main._has_sendable_profile():
                if main._has_sendable_profile(ignore_human_break=True):
                    wait = min(60.0, main._seconds_until_any_human_break_ends())
                    end_at = time.monotonic() + wait
                    while time.monotonic() < end_at:
                        main._touch_worker_activity()
                        await asyncio.sleep(min(15.0, end_at - time.monotonic()))
                    continue
                worker_shutdown(
                    "Готово: дневные лимиты всех аккаунтов исчерпаны"
                    if main._campaign_goal() == "daily_limits"
                    else "Некому отправлять: нет активных профилей или дневной лимит исчерпан"
                )
                return
            # в этой группе некого — переходим к следующей
            with main._conn() as c:
                c.execute(
                    "UPDATE queue_state SET profile_idx=?, group_idx=? WHERE id=1",
                    (pi, main.next_index(gi, len(groups))),
                )
            open_ids = [p["id"] for p in profiles if main._is_circuit_open(p["id"])]
            if open_ids and len(open_ids) >= len(profiles):
                main.append_log(
                    "Все профили группы в автопаузе — следующая группа"
                )
            await asyncio.sleep(1)
            main._touch_worker_activity()


async def pool_supervisor() -> None:
    
    n = main._pool_size()
    RUNTIME.pool_done_announced = False
    main.append_log(f"Пул воркеров: {n} параллельных")
    RUNTIME.pool_tasks = [asyncio.create_task(poolworker_loop(i + 1)) for i in range(n)]
    try:
        await asyncio.gather(*RUNTIME.pool_tasks)
    except asyncio.CancelledError:
        for t in RUNTIME.pool_tasks:
            t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*RUNTIME.pool_tasks, return_exceptions=True)
        raise
    finally:
        RUNTIME.pool_tasks = []


def scheduler_tenant_ids() -> list[int | None]:
    if not main._is_server_mode():
        return [None]
    from app import db_pg

    try:
        rows = db_pg.list_tenants_with_users()
        return [int(r["tenant_id"]) for r in rows] or [None]
    except Exception:
        return [None]


async def scheduler_tick() -> None:
    with main._conn() as c:
        row = c.execute("SELECT * FROM campaign_schedule WHERE id=1").fetchone()
    if row and row["enabled"] and row["start_at"]:
        start_at = main._parse_iso_datetime(row["start_at"])
        now = datetime.now(timezone.utc)
        rt = REGISTRY.worker()
        worker_busy = rt.worker_task and not rt.worker_task.done()
        if now >= start_at and not worker_busy:
            with main._conn() as c:
                c.execute("UPDATE campaign_schedule SET enabled=0 WHERE id=1")
            main.append_log(
                f"Расписание: старт кампании (запланировано на {row['start_at']})"
            )
            try:
                main._require_vault_unlocked()
            except HTTPException as e:
                main.append_log(f"Расписание: пропуск — {e.detail}")
            else:
                if main.load_message_pool() and main._has_sendable_profile():
                    await start_worker(scheduled_for=row["start_at"])
                else:
                    main.append_log("Расписание: нет сообщений или профилей — пропуск")
    await main._try_auto_resume(log_prefix="Автовозобновление")


async def scheduler_loop() -> None:
    from app.tenant import tenant_scope

    while True:
        await asyncio.sleep(15)
        if REGISTRY.app.shutting_down:
            return
        for tid in scheduler_tenant_ids():
            try:
                with tenant_scope(tenant_id=tid):
                    await scheduler_tick()
            except Exception as e:
                main.append_log(f"Ошибка планировщика (tenant={tid}): {e}")


async def watchdog_loop() -> None:
    while True:
        await asyncio.sleep(60)
        if REGISTRY.app.shutting_down:
            return
        for key, rt in REGISTRY.worker_items():
            if not rt.worker_task or rt.worker_task.done():
                continue
            idle = time.monotonic() - rt.worker_last_activity
            if idle <= main.WORKER_TIMEOUT:
                continue
            tid = REGISTRY._tenant_from_key(key)
            main.append_log(
                f"Сторож: воркер tenant={tid or 'local'} завис "
                f"({idle:.0f}с без активности) — перезапуск"
            )
            if rt.worker_ctx_snapshot is not None:
                from app.tenant import restore_context, clear_context

                restore_context(rt.worker_ctx_snapshot)
                try:
                    await stop_worker(
                        finish_status="stopped",
                        reason="Перезапуск сторожем",
                        tenant_id=tid,
                    )
                    await start_worker(record_campaign=False)
                finally:
                    clear_context()
            else:
                await stop_worker(
                    finish_status="stopped",
                    reason="Перезапуск сторожем",
                    tenant_id=tid,
                )
                await start_worker(record_campaign=False)

async def start_worker(
    *,
    record_campaign: bool = True,
    scheduled_for: str | None = None,
) -> None:
    """Запуск воркера / пула без сброса индексов прогресса."""
    from app.tenant import clear_context, get_tenant_id, restore_context, snapshot_context

    ctx_snap = snapshot_context()
    tid = get_tenant_id()
    rt = REGISTRY.worker_for(tid)

    async def _worker_task() -> None:
        restore_context(ctx_snap)
        rt.worker_ctx_snapshot = ctx_snap
        rt.tenant_id = tid
        try:
            if main._pool_size() > 1:
                await pool_supervisor()
            else:
                await worker_loop()
        finally:
            clear_context()

    async with rt.worker_lock:
        if rt.worker_task and not rt.worker_task.done():
            return
        rt.touch_activity()
        rt.pool_done_announced = False
        await main._preflight_group_proxies()
        with main._conn() as c:
            c.execute("UPDATE queue_state SET running=1 WHERE id=1")
            msgs = main.load_message_pool()
            if main._message_pick_mode() == "random_norepeat" and msgs:
                qs = c.execute("SELECT message_idx FROM queue_state WHERE id=1").fetchone()
                if int(qs["message_idx"] if qs else 0) == 0 and not main._get_message_bag(c):
                    bag = list(range(len(msgs)))
                    random.shuffle(bag)
                    main._set_message_bag(c, bag)
        if record_campaign:
            begin_campaign(scheduled_for=scheduled_for)
            main._metric_inc("campaigns_started_total")
        clear_context()
        try:
            rt.worker_task = asyncio.create_task(_worker_task())
        finally:
            restore_context(ctx_snap)


def reset_queue_progress() -> None:
    n = len(main.load_message_pool())
    with main._conn() as c:
        c.execute(
            "UPDATE queue_state SET profile_idx=0, message_idx=0, group_idx=0 WHERE id=1"
        )
    main._rebuild_message_bag(n)


async def stop_worker(
    *,
    finish_status: str | None = "stopped",
    reason: str = "Остановлено пользователем",
    tenant_id: int | None = None,
) -> None:
    from app.tenant import get_tenant_id

    if tenant_id is None:
        tenant_id = get_tenant_id()
    rt = REGISTRY.worker_for(tenant_id)
    was_running = bool(rt.worker_task and not rt.worker_task.done())
    with main._conn() as c:
        c.execute("UPDATE queue_state SET running=0 WHERE id=1")
    if rt.worker_task:
        rt.worker_task.cancel()
        try:
            await rt.worker_task
        except asyncio.CancelledError:
            pass
        rt.worker_task = None
    for t in list(rt.pool_tasks):
        t.cancel()
    rt.pool_tasks = []
    if was_running and finish_status:
        with main._conn() as c:
            still = c.execute(
                "SELECT 1 FROM campaigns WHERE status='running' LIMIT 1"
            ).fetchone()
        if still:
            finish_campaign(finish_status, reason)
            main._metric_inc("campaigns_finished_total")
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(notify_campaign_end(finish_status, reason))
            except RuntimeError:
                pass


async def stop_all_workers(
    *,
    finish_status: str | None = "stopped",
    reason: str = "Остановка сервера",
) -> None:
    from app.tenant import clear_context, restore_context

    for key, rt in list(REGISTRY.worker_items()):
        tid = REGISTRY._tenant_from_key(key)
        if rt.worker_ctx_snapshot is not None:
            restore_context(rt.worker_ctx_snapshot)
            try:
                await stop_worker(
                    finish_status=finish_status,
                    reason=reason,
                    tenant_id=tid,
                )
            finally:
                clear_context()
        else:
            await stop_worker(
                finish_status=finish_status,
                reason=reason,
                tenant_id=tid,
            )
