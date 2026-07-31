"""Ops monitoring: health-derived alerts via Telegram."""

from __future__ import annotations

import asyncio
import os
import time
from app.runtime import main as m

_DEDUPE_SEC = 900.0
_last_alert: dict[str, float] = {}
_CHECK_INTERVAL_SEC = 120.0


def _main():

    return m


def _should_alert(key: str) -> bool:
    now = time.time()
    if now - _last_alert.get(key, 0.0) < _DEDUPE_SEC:
        return False
    _last_alert[key] = now
    return True


async def ops_alert_loop() -> None:
    """Periodic ops alerts when PG/Redis unhealthy or circuit breaker high."""
    from app.campaign_runtime import REGISTRY

    m = _main()
    threshold = int(os.environ.get("OPS_CIRCUIT_ALERT_THRESHOLD", "10") or "10")
    while True:
        await asyncio.sleep(_CHECK_INTERVAL_SEC)
        if REGISTRY.app.shutting_down or not m._is_server_mode():
            return
        try:
            await _tick(threshold)
        except Exception as e:
            m.append_log(f"Ops alert loop: {e}")


async def _tick(circuit_threshold: int) -> None:
    from app import auth_rate_limit, db_pg

    m = _main()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return

    if not db_pg.ping():
        if _should_alert("pg_down"):
            m._schedule_telegram(
                "Ops: PostgreSQL недоступен",
                ["Проверьте postgres и DATABASE_URL."],
                dedupe_key="ops:pg_down",
            )

    redis_url = os.environ.get("REDIS_URL", "").strip()
    if redis_url:
        r = auth_rate_limit._get_redis()
        if r is None and _should_alert("redis_down"):
            m._schedule_telegram(
                "Ops: Redis недоступен",
                ["REDIS_URL задан, но ping не прошёл. Rate limit / Celery могут деградировать."],
                dedupe_key="ops:redis_down",
            )

    open_n = m._circuit_open_count()
    if open_n >= circuit_threshold and _should_alert(f"circuit:{open_n // circuit_threshold}"):
        m._schedule_telegram(
            "Ops: много профилей в circuit breaker",
            [f"Открытых circuit: {open_n} (порог {circuit_threshold})."],
            dedupe_key=f"ops:circuit:{open_n}",
        )


def reset_for_tests() -> None:
    _last_alert.clear()
