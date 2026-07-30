"""Subscription lifecycle: expiry warnings, worker stop on expiry."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any

_WARN_DAYS = (7, 1)
_CHECK_INTERVAL_SEC = 3600.0
_last_warn_day: dict[tuple[int, int], str] = {}
_stopped_expired: set[int] = set()
_last_revoke_cleanup_day: str = ""


def _main():
    import main as m

    return m


async def subscription_lifecycle_loop() -> None:
    """Hourly: warn admin about expiring subs; stop workers on expiry."""
    from app.campaign_runtime import REGISTRY

    m = _main()
    while True:
        await asyncio.sleep(_CHECK_INTERVAL_SEC)
        if REGISTRY.app.shutting_down or not m._is_server_mode():
            return
        try:
            await _tick()
        except Exception as e:
            m.append_log(f"Subscription lifecycle: {e}")


async def _tick() -> None:
    from app import db_pg

    m = _main()
    today = datetime.now(timezone.utc).date().isoformat()

    global _last_revoke_cleanup_day
    if _last_revoke_cleanup_day != today:
        try:
            n = await asyncio.to_thread(db_pg.cleanup_revoked_tokens)
            if n:
                m.append_log(f"Очистка revoked_tokens: удалено {n}")
        except Exception as e:
            m.append_log(f"Очистка revoked_tokens: {e}")
        _last_revoke_cleanup_day = today

    for days in _WARN_DAYS:
        for row in db_pg.list_expiring_subscriptions(within_days=days):
            tid = int(row["tenant_id"])
            key = (tid, days)
            if _last_warn_day.get(key) == today:
                continue
            exp = row["expires_at"]
            exp_s = exp.isoformat()[:10] if hasattr(exp, "isoformat") else str(exp)[:10]
            left = row.get("days_left")
            m._schedule_telegram(
                f"Подписка истекает через {days} дн.",
                [
                    f"Учреждение: {row['institution_name']} (#{tid})",
                    f"Email: {row['email']}",
                    f"До: {exp_s} (осталось ~{left} дн.)",
                ],
                dedupe_key=f"sub_warn:{tid}:{days}:{today}",
            )
            _last_warn_day[key] = today

    for row in db_pg.tenants_recently_expired(since_hours=25):
        tid = int(row["tenant_id"])
        if tid in _stopped_expired:
            continue
        if not db_pg.subscription_active(tid):
            await _stop_tenant_worker(tid, row)
            _stopped_expired.add(tid)
            exp = row["expired_at"]
            exp_s = exp.isoformat()[:10] if hasattr(exp, "isoformat") else str(exp)[:10]
            m._schedule_telegram(
                "Подписка истекла",
                [
                    f"Учреждение: {row['institution_name']} (#{tid})",
                    f"Email: {row['email']}",
                    f"Истекла: {exp_s}",
                    "Рассылка остановлена (если была активна).",
                ],
                dedupe_key=f"sub_expired:{tid}:{today}",
            )


async def _stop_tenant_worker(tid: int, row: dict[str, Any]) -> None:
    from app.campaign_runtime import REGISTRY
    from app.tenant import tenant_scope

    m = _main()
    rt = REGISTRY.worker_for(tid)
    if not rt.worker_task or rt.worker_task.done():
        return
    with tenant_scope(tenant_id=tid):
        await m._stop_worker(
            finish_status="stopped",
            reason="Подписка истекла",
            tenant_id=tid,
        )


def reset_for_tests() -> None:
    global _last_revoke_cleanup_day
    _last_warn_day.clear()
    _stopped_expired.clear()
    _last_revoke_cleanup_day = ""
