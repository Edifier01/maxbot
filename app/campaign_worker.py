"""Campaign worker orchestration (extracted from main.py)."""

from __future__ import annotations

import asyncio
import contextlib
import http.client
import ipaddress
import json
import os
import random
import sqlite3
import socket
import ssl
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException

from app.config import webhook_url_allowed
from app.runtime import main
from app.campaign_runtime import REGISTRY, RUNTIME
from app.campaign_queue import MessageBagIntegrityError
from app.campaign_send import (
    SendTracker,
    recover_inflight_operations,
    send_with_retry,
    sleep_send_delay,
)


class MigrationReviewRequired(RuntimeError):
    """Legacy budget history is contradictory and cannot receive a fresh target."""

    def __init__(self, findings: tuple[dict[str, object], ...]) -> None:
        self.findings = findings
        super().__init__("MIGRATION_REVIEW_REQUIRED")


def legacy_budget_migration_report() -> tuple[dict[str, object], ...]:
    """Return the credential-free legacy budget gate for the current day."""
    from app.services.legacy_daily_budget import inspect_legacy_daily_budgets

    business_date = main._local_today().isoformat()
    with main._conn() as connection:
        return tuple(
            finding.as_dict()
            for finding in inspect_legacy_daily_budgets(connection, business_date)
        )


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


def materialize_daily_plans() -> int:
    """Pin one account/day plan per eligible account from the current library."""
    from app.repositories.daily_plans import DailyPlanRepository
    from app.repositories.message_sets import MessageSetRepository
    from app.services.daily_plans import DailyPlanService, LibraryItem
    from app.services.legacy_daily_budget import inspect_legacy_daily_budgets

    plan_connection, plan_scope = _daily_plan_storage()
    plan_repository = DailyPlanRepository(plan_connection)
    business_date = main._local_today().isoformat()
    legacy_findings = inspect_legacy_daily_budgets(plan_connection, business_date)
    review_findings = tuple(
        finding.as_dict()
        for finding in legacy_findings
        if finding.status == "MIGRATION_REVIEW_REQUIRED"
    )
    if review_findings:
        raise MigrationReviewRequired(review_findings)
    # A new business date expires only unclaimed historical slots. Unknown or
    # accepted outcomes stay occupied and are never converted into catch-up work.
    plan_repository.expire_before(plan_scope, business_date)
    accepted_by_profile = {
        finding.profile_id: int(finding.accepted_today or 0)
        for finding in legacy_findings
    }
    library_connection, library_scope = main._message_library_source_storage()
    message_sets = MessageSetRepository(library_connection)
    version = message_sets.current(library_scope)
    if version is None:
        return 0
    library_items = tuple(
        LibraryItem(
            item_id=str(row["item_id"]),
            text=str(row["text"]),
            version_id=str(version["version_id"]),
        )
        for row in message_sets.items(library_scope, str(version["version_id"]))
    )
    service = DailyPlanService(plan_repository)
    selected: dict[int, tuple[Any, Any]] = {}
    for group in main._active_groups():
        for profile in main._active_profiles_for_group(int(group["id"])):
            selected.setdefault(int(profile["id"]), (profile, group))
    materialized = 0
    for profile, group in selected.values():
        role = str(profile["day_role"] or "active") if "day_role" in profile.keys() else "active"
        service.materialize_day(
            plan_scope,
            int(profile["id"]),
            business_date,
            sampled_limit=main._ensure_daily_limit(int(profile["id"]), log=False),
            role=role,
            quiet_limit=main._quiet_limit(),
            work_group_id=int(group["id"]),
            library_items=library_items,
            mode=main._message_pick_mode(),
            accepted_count=accepted_by_profile.get(int(profile["id"]), 0),
        )
        materialized += 1
    return materialized


def _daily_plan_storage() -> tuple[sqlite3.Connection, str]:
    """Return tenant-local plan storage and its durable scope key."""
    connection = main._conn()
    if not main._is_server_mode():
        return connection, "local"
    from app.tenant import get_tenant_id

    tenant_id = get_tenant_id()
    return connection, f"tenant:{int(tenant_id)}" if tenant_id is not None else "global"


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


_MAX_HTTP_RESPONSE_BYTES = 64 * 1024


def _public_addresses(host: str, port: int) -> tuple[str, ...]:
    """Resolve once and reject any non-public destination before connecting."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise RuntimeError("webhook_dns_resolution_failed") from exc

    addresses: list[str] = []
    for _family, _socktype, _proto, _canonname, sockaddr in infos:
        address = str(sockaddr[0])
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        if not parsed.is_global:
            raise RuntimeError("webhook_destination_not_public")
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise RuntimeError("webhook_dns_resolution_failed")
    return tuple(addresses)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that keeps TLS SNI while pinning the TCP address."""

    def __init__(self, host: str, port: int, address: str, timeout: float) -> None:
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self._destination_address = address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._destination_address, self.port), self.timeout
        )
        if self._tunnel_host:
            self._tunnel()
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def _post_json_to_address(
    url: str,
    payload: dict[str, Any],
    address: str,
    timeout: float,
) -> None:
    parsed = urlsplit(url)
    host = parsed.hostname
    if parsed.scheme != "https" or not host:
        raise RuntimeError("webhook_https_required")
    port = parsed.port or 443
    target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    connection = _PinnedHTTPSConnection(host, port, address, timeout)
    try:
        connection.request(
            "POST",
            target,
            body=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "MAX-Sender/1.4",
                "Content-Length": str(len(data)),
            },
        )
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise RuntimeError("webhook_redirect_rejected")
        if not 200 <= response.status < 300:
            raise RuntimeError(f"webhook_http_{response.status}")
        if len(response.read(_MAX_HTTP_RESPONSE_BYTES + 1)) > _MAX_HTTP_RESPONSE_BYTES:
            raise RuntimeError("webhook_response_too_large")
    finally:
        connection.close()


def http_post_json(url: str, payload: dict[str, Any], timeout: float = 15) -> None:
    """POST bounded JSON without redirects or DNS-rebinding egress."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError("webhook_https_required")
    addresses = _public_addresses(parsed.hostname, parsed.port or 443)
    last_error: Exception | None = None
    for address in addresses:
        try:
            _post_json_to_address(url, payload, address, timeout)
            return
        except (OSError, RuntimeError) as exc:
            last_error = exc
    raise RuntimeError("webhook_request_failed") from last_error


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
    if webhook and not webhook_url_allowed(webhook):
        main.append_log("Вебхук отключён: URL не входит в WEBHOOK_ALLOWED_HOSTS")
    elif webhook:
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

def _done_or_wait() -> str | None:
    """DONE only when the bag is empty and no other worker holds a claim."""
    if RUNTIME.jobs_in_flight > 0:
        return None
    if not RUNTIME.pool_done_announced:
        RUNTIME.pool_done_announced = True
        return "DONE"
    return "STOP"


def _restore_claim(job: dict[str, Any], tracker: SendTracker) -> None:
    """Restore a pool claim only while MAX send is proven not started."""
    if not tracker.may_requeue:
        return
    before = job.get("queue_before")
    if not isinstance(before, dict):
        main._return_to_message_bag(int(job["mi"]))
        return
    with main._conn() as c:
        c.execute(
            "UPDATE queue_state SET profile_idx=?, message_idx=?, group_idx=?, "
            "message_bag=? WHERE id=1",
            (
                int(before["profile_idx"]),
                int(before["message_idx"]),
                int(before["group_idx"]),
                str(before["message_bag"] or "[]"),
            ),
        )


def _daily_library_current() -> bool:
    from app.repositories.message_sets import MessageSetRepository

    connection, scope = main._message_library_source_storage()
    return MessageSetRepository(connection).current(scope) is not None


def _campaign_control_scope() -> str:
    if not main._is_server_mode():
        return "local"
    from app.tenant import get_tenant_id

    tenant_id = get_tenant_id()
    return f"tenant:{int(tenant_id)}" if tenant_id is not None else "global"


def _campaign_control_allows_claim(expected_generation: int | None = None) -> bool:
    """Fence worker claims after a persisted Stop without requiring new schema on legacy DBs."""

    scope = _campaign_control_scope()
    if not scope:
        return False
    try:
        with main._conn() as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='campaign_control'"
            ).fetchone()
            if table is None:
                return True
            control = connection.execute(
                "SELECT generation, auto_run, stop_requested, state "
                "FROM campaign_control WHERE scope=?",
                (scope,),
            ).fetchone()
    except sqlite3.Error:
        return False
    if control is None:
        return False
    if int(control["auto_run"]) != 1 or int(control["stop_requested"]) != 0:
        return False
    if str(control["state"]) != "running":
        return False
    return expected_generation is None or int(control["generation"]) == int(expected_generation)


def _daily_eligible_assignments() -> tuple[tuple[int, int], ...]:
    """Return currently eligible pinned account/group pairs.

    Daily slots are already allocated, so this deliberately does not apply the
    free-capacity check.  It still fences disabled groups, role=skip, circuit
    breakers, cooldowns, and human breaks before claiming a slot.
    """

    assignments: list[tuple[int, int]] = []
    for group in main._active_groups():
        group_id = int(group["id"])
        if group_id in RUNTIME.groups_in_flight:
            continue
        for profile in main._active_profiles_for_group(group_id):
            profile_id = int(profile["id"])
            if not main._automation_scope_allows_external_action(profile_id, group_id):
                continue
            if main._is_circuit_open(profile_id):
                continue
            if main._is_in_cooldown(profile):
                continue
            if main._is_in_human_break(profile_id):
                continue
            assignments.append((profile_id, group_id))
    return tuple(assignments)


def _daily_wait_state(connection: sqlite3.Connection, scope: str) -> str:
    today = main._local_today().isoformat()
    plans = connection.execute(
        "SELECT plan_id, status, target FROM profile_daily_plans "
        "WHERE scope=? AND business_date=?",
        (scope, today),
    ).fetchall()
    if not plans:
        return "DAILY_WAIT"
    if RUNTIME.jobs_in_flight > 0:
        return "DAILY_WAIT"
    if any(str(plan["status"]) == "waiting_pool" for plan in plans):
        return "DAILY_WAIT"
    pending = connection.execute(
        "SELECT COUNT(*) AS n FROM profile_message_slots s "
        "JOIN profile_daily_plans p ON p.plan_id=s.plan_id "
        "WHERE s.scope=? AND p.business_date=? "
        "AND s.status IN ('queued', 'claimed', 'in_flight')",
        (scope, today),
    ).fetchone()
    if int(pending["n"] if pending else 0) > 0:
        return "DAILY_WAIT"
    return "DAILY_DONE"


def _cancel_daily_slots_for_revoked_scopes(
    connection: sqlite3.Connection, scope: str
) -> int:
    """Fence queued personal slots after persisted consent revocation."""
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='profile_automation_scope'"
    ).fetchone()
    if table is None:
        return 0
    revoked = connection.execute(
        "SELECT profile_id FROM profile_automation_scope "
        "WHERE consent_state != 'active'"
    ).fetchall()
    if not revoked:
        return 0
    from app.repositories.daily_plans import DailyPlanRepository
    from app.services.daily_plans import DailyPlanService

    service = DailyPlanService(DailyPlanRepository(connection))
    return sum(
        service.cancel_queued_for_profile(
            scope, int(row["profile_id"]), "CONSENT_REVOKED"
        )
        for row in revoked
    )


def _claim_daily_job_sync() -> dict[str, Any] | str | None:
    """Claim one existing personal slot; ``None`` keeps legacy mode available."""

    if not _daily_library_current():
        return None
    from app.repositories.daily_plans import DailyPlanRepository
    from app.services.daily_plans import DailyPlanService, WaitDecision

    connection, scope = _daily_plan_storage()
    _cancel_daily_slots_for_revoked_scopes(connection, scope)
    service = DailyPlanService(DailyPlanRepository(connection))
    decision = service.claim_next_slot(
        scope,
        datetime.now(timezone.utc),
        eligible_assignments=_daily_eligible_assignments(),
    )
    if isinstance(decision, WaitDecision):
        return _daily_wait_state(connection, scope)
    profile_id = int(decision.profile_id)
    group_id = int(decision.work_group_id) if decision.work_group_id is not None else None
    if group_id is None:
        service.retry_slot(decision.slot_id, proof_no_send=True)
        return "DAILY_WAIT"
    with main._conn() as current:
        profile = current.execute(
            "SELECT * FROM profiles WHERE id=?", (profile_id,)
        ).fetchone()
        group = current.execute(
            "SELECT * FROM groups WHERE id=?", (group_id,)
        ).fetchone()
        ordinal = current.execute(
            "SELECT ordinal FROM profile_message_slots WHERE slot_id=?",
            (decision.slot_id,),
        ).fetchone()
    if profile is None or group is None:
        service.retry_slot(decision.slot_id, proof_no_send=True)
        return "DAILY_WAIT"
    return {
        "profile": profile,
        "group": group,
        "text": decision.rendered_text,
        "mi": int(ordinal["ordinal"] if ordinal else 0),
        "pi": 0,
        "gi_next": 0,
        "mi_next": 0,
        "queue_before": None,
        "daily_plan_id": decision.plan_id,
        "slot_id": decision.slot_id,
        "daily_plan": True,
    }


def _finalize_daily_job(
    job: dict[str, Any], sent: bool, tracker: SendTracker
) -> None:
    slot_id = str(job.get("slot_id") or "").strip()
    if not slot_id:
        return
    from app.repositories.daily_plans import DailyPlanRepository
    from app.services.daily_plans import DailyPlanService

    connection, _scope = _daily_plan_storage()
    service = DailyPlanService(DailyPlanRepository(connection))
    try:
        if sent or tracker.provider_message_id:
            service.mark_slot_accepted(slot_id)
        elif tracker.may_requeue:
            operation = None
            if tracker.operation_ledger is not None and tracker.operation_id:
                operation = tracker.operation_ledger.get(tracker.operation_id)
            if operation is None or (
                operation.status == "failed_unsent"
                and operation.pre_effect_retry_count < operation.max_pre_effect_retries
            ):
                service.retry_slot(slot_id, proof_no_send=True)
            else:
                service.mark_slot_failed_unsent(
                    slot_id, tracker.error or "bounded pre-send retries exhausted"
                )
        else:
            service.mark_slot_unknown(slot_id, tracker.error or "send outcome unknown")
    except Exception as exc:
        main.append_log(f"Не удалось завершить daily slot {slot_id}: {exc}")


def _claim_next_job_sync() -> dict[str, Any] | str | None:
    """Синхронное тело claim_next_job (SQLite под asyncio.to_thread)."""
    if REGISTRY.app.shutting_down:
        return "STOP"
    if not _campaign_control_allows_claim():
        return "STOP"
    with main._conn() as c:
        qs = c.execute("SELECT * FROM queue_state WHERE id=1").fetchone()
        if not qs or not qs["running"]:
            return "STOP"
        main._reset_daily_counts(c)

    daily_job = _claim_daily_job_sync()
    if daily_job is not None:
        return daily_job

    messages = main.load_message_pool()
    groups = main._active_groups()
    if not messages or not groups:
        return None

    with main._conn() as c:
        qs = c.execute("SELECT * FROM queue_state WHERE id=1").fetchone()
        if not qs or not qs["running"]:
            return "STOP"
        pi, mi, gi = qs["profile_idx"], qs["message_idx"], qs["group_idx"]
        queue_before = {
            "profile_idx": pi,
            "message_idx": mi,
            "group_idx": gi,
            "message_bag": qs["message_bag"],
        }

        if main._campaign_goal() == "message_pool":
            if main._message_pick_mode() == "random_norepeat":
                bag = main._ensure_message_bag(c, len(messages))
                if not bag:
                    return _done_or_wait()
            elif mi >= len(messages):
                return _done_or_wait()

        n_groups = len(groups)
        in_flight = RUNTIME.groups_in_flight
        profile = None
        group = None
        picked_gidx = gi % n_groups
        for offset in range(n_groups):
            gidx = (gi + offset) % n_groups
            cand_group = groups[gidx]
            gid = int(cand_group["id"])
            if gid in in_flight:
                continue
            profiles = main._active_profiles_for_group(gid)
            if not profiles:
                continue
            attempts = 0
            while attempts < len(profiles):
                cand = profiles[pi % len(profiles)]
                pi = main.next_index(pi, len(profiles))
                attempts += 1
                if main._is_circuit_open(cand["id"]):
                    continue
                if not main._can_send_in_group(cand, gid):
                    continue
                if main._reserved_hits_daily_limit(cand):
                    continue
                profile = cand
                break
            if profile is not None:
                group = cand_group
                picked_gidx = gidx
                break

        if profile is None or group is None:
            if not main._has_active_profiles():
                if not RUNTIME.pool_done_announced:
                    RUNTIME.pool_done_announced = True
                    return "NO_PROFILES"
                return "STOP"
            return None

        picked = main._pick_next_message(c, messages, mi)
        if picked is None:
            return _done_or_wait()

        text, pool_idx, progress_next, bag_mode = picked
        gi_next = main.next_index(picked_gidx, n_groups)
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
            "queue_before": queue_before,
        }


async def claim_next_job() -> dict[str, Any] | str | None:
    """Атомарно взять следующее сообщение для пула.

    Returns:
      dict — задача
      \"DONE\" — очередь исчерпана (первый воркер должен завершить кампанию)
      \"STOP\" — running=0 или уже объявлен DONE
      None — временно нечего делать (группа занята другим воркером, нет профилей и т.п.)
    """
    async with RUNTIME.claim_lock:
        job = _claim_next_job_sync()
        if isinstance(job, dict):
            RUNTIME.groups_in_flight.add(int(job["group"]["id"]))
            RUNTIME.jobs_in_flight += 1
            pid = int(job["profile"]["id"])
            RUNTIME.profile_reserved[pid] = RUNTIME.profile_reserved.get(pid, 0) + 1
        return job


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
        if REGISTRY.app.shutting_down:
            main.append_log(f"Воркер пула #{worker_id} остановлен (shutdown)")
            return
        if await main._wait_if_outside_send_window():
            continue
        try:
            job = await claim_next_job()
        except MessageBagIntegrityError as exc:
            worker_shutdown(f"Остановлено: повреждена legacy-колода ({exc})")
            return
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
        if job == "DAILY_DONE":
            worker_shutdown("Готово: дневные планы выполнены")
            return
        if job == "DAILY_WAIT":
            await asyncio.sleep(2)
            continue
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

        group_id = int(job["group"]["id"])
        daily_job = bool(job.get("daily_plan"))
        sent = False
        tracker = SendTracker()
        try:
            try:
                sent = await send_with_retry(
                    job["profile"],
                    job["group"],
                    job["text"],
                    job["mi"],
                    job["pi"],
                    job["gi_next"],
                    job["mi_next"],
                    advance_queue=False,
                    tracker=tracker,
                    daily_plan_id=job.get("daily_plan_id"),
                    slot_id=job.get("slot_id"),
                )
            except asyncio.CancelledError:
                if daily_job:
                    _finalize_daily_job(job, False, tracker)
                else:
                    _restore_claim(job, tracker)
                raise
        finally:
            RUNTIME.groups_in_flight.discard(group_id)
            RUNTIME.jobs_in_flight = max(0, RUNTIME.jobs_in_flight - 1)
            pid = int(job["profile"]["id"])
            left = int(RUNTIME.profile_reserved.get(pid, 0)) - 1
            if left <= 0:
                RUNTIME.profile_reserved.pop(pid, None)
            else:
                RUNTIME.profile_reserved[pid] = left
        if daily_job:
            _finalize_daily_job(job, sent, tracker)
        elif not sent:
            _restore_claim(job, tracker)
        if not sent:
            await asyncio.sleep(3)
            main._touch_worker_activity()
            continue
        await sleep_send_delay(pool_scale=True)


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
        return [int(r["tenant_id"]) for r in rows]
    except Exception:
        main.append_log("Планировщик: PostgreSQL недоступен — tenant scan пропущен")
        return []


async def scheduler_tick() -> None:
    if main._is_server_mode():
        from app.tenant import get_tenant_id
        from app import db_pg

        tid = get_tenant_id()
        if tid is not None and not db_pg.subscription_active(tid):
            main.set_setting("auto_run", "0")
            main.append_log(
                f"Планировщик: подписка не активна (tenant={tid}) — пропуск"
            )
            return
    with main._conn() as c:
        row = c.execute("SELECT * FROM campaign_schedule WHERE id=1").fetchone()
    if row and row["enabled"] and row["start_at"]:
        start_at = main._parse_iso_datetime(row["start_at"])
        now = datetime.now(timezone.utc)
        rt = REGISTRY.worker()
        worker_busy = rt.worker_task and not rt.worker_task.done()
        if now >= start_at and not worker_busy:
            main.append_log(
                f"Расписание: старт кампании (запланировано на {row['start_at']})"
            )
            try:
                main._require_vault_unlocked()
            except HTTPException as e:
                main.append_log(f"Расписание: пропуск — {e.detail}")
            else:
                if main.load_message_pool() and main._has_sendable_profile():
                    if not _campaign_control_allows_claim():
                        main.append_log(
                            "Расписание: запуск заблокирован сохранённой командой Stop"
                        )
                    else:
                        await main._preflight_group_proxies()
                        started = await start_worker(scheduled_for=row["start_at"])
                        if started:
                            main.set_setting("auto_run", "1")
                            with main._conn() as c:
                                c.execute(
                                    "UPDATE campaign_schedule SET enabled=0 WHERE id=1"
                                )
                        else:
                            main.append_log(
                                "Расписание: воркер занят — запуск сохранён для повтора"
                            )
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
                with tenant_scope(tenant_id=tid):
                    main.append_log(f"Ошибка планировщика: {e}")


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
            snapshot = rt.worker_ctx_snapshot
            if snapshot is not None:
                from app.tenant import restore_context, clear_context

                restore_context(snapshot)
            try:
                await stop_worker(
                    finish_status=None,
                    reason="Перезапуск сторожем",
                    tenant_id=tid,
                )
                if main._auto_run_enabled():
                    if await start_worker(record_campaign=False):
                        main._metric_inc("worker_restarts_total")
            except Exception as e:
                main.append_log(
                    f"Сторож: перезапуск tenant={tid or 'local'} не удался — {e}"
                )
            finally:
                if snapshot is not None:
                    clear_context()

async def start_worker(
    *,
    record_campaign: bool = True,
    scheduled_for: str | None = None,
    control_generation: int | None = None,
    preflight: bool = True,
) -> bool:
    """Запуск воркера / пула без сброса индексов прогресса."""
    from app.tenant import clear_context, get_tenant_id, restore_context, snapshot_context

    if REGISTRY.app.shutting_down:
        return False
    ctx_snap = snapshot_context()
    tid = get_tenant_id()
    rt = REGISTRY.worker_for(tid)

    async def _worker_task() -> None:
        restore_context(ctx_snap)
        rt.worker_ctx_snapshot = ctx_snap
        rt.tenant_id = tid
        main._load_antiban_state()
        try:
            await pool_supervisor()
        finally:
            clear_context()

    async with REGISTRY.app.message_pool_lock:
        async with rt.worker_lock:
            if REGISTRY.app.shutting_down:
                return False
            if rt.worker_task and not rt.worker_task.done():
                return False
            if not _campaign_control_allows_claim(control_generation):
                return False
            rt.touch_activity()
            rt.pool_done_announced = False
            materialized_plans = materialize_daily_plans()
            if materialized_plans:
                main.append_log(
                    f"Подготовлены дневные планы аккаунтов: {materialized_plans}"
                )
            recovered_operations = recover_inflight_operations()
            if recovered_operations:
                main.append_log(
                    "Восстановлены незавершённые операции отправки: "
                    + ", ".join(recovered_operations)
                )
            if preflight:
                await main._preflight_group_proxies()
            if not _campaign_control_allows_claim(control_generation):
                return False
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
    return True


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
    from app.tenant import get_tenant_id, tenant_scope

    if tenant_id is None:
        tenant_id = get_tenant_id()
    scope = (
        tenant_scope(tenant_id=tenant_id)
        if tenant_id is not None
        else contextlib.nullcontext()
    )
    with scope:
        rt = REGISTRY.worker_for(tenant_id)
        was_running = bool(rt.worker_task and not rt.worker_task.done())
        db_path = main._db_path()
        if db_path.is_file():
            try:
                with main._conn() as c:
                    c.execute("UPDATE queue_state SET running=0 WHERE id=1")
            except sqlite3.OperationalError:
                pass
        current = asyncio.current_task()
        called_from_supervisor = current is not None and current is rt.worker_task
        called_from_pool = current is not None and current in rt.pool_tasks
        called_from_inside = called_from_supervisor or called_from_pool
        if rt.worker_task:
            rt.worker_task.cancel()
            if not called_from_inside:
                try:
                    await rt.worker_task
                except asyncio.CancelledError:
                    pass
            rt.worker_task = None
        for t in list(rt.pool_tasks):
            if t is current:
                continue
            t.cancel()
        rt.pool_tasks = []
        if was_running and finish_status and db_path.is_file():
            still = None
            try:
                with main._conn() as c:
                    still = c.execute(
                        "SELECT 1 FROM campaigns WHERE status='running' LIMIT 1"
                    ).fetchone()
            except sqlite3.OperationalError:
                still = None
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
