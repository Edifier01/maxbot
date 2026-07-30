"""Health, metrics, status, WebSocket."""

from __future__ import annotations

import asyncio
import contextlib

import jwt
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["monitor"])


def _authenticate_ws(ws: WebSocket) -> bool:
    """Return True if connection may proceed. Server mode: JWT ?token=."""
    import main as m

    from app import db_pg
    from app.auth import decode_token
    from app.config import is_server_mode
    from app.tenant import set_context

    if is_server_mode():
        token = (ws.query_params.get("token") or "").strip()
        if not token:
            return False
        try:
            payload = decode_token(token)
        except jwt.PyJWTError:
            return False
        jti = payload.get("jti")
        if jti and db_pg.is_token_revoked(jti):
            return False
        user_id = int(payload["sub"])
        if not db_pg.get_user_by_id(user_id):
            return False
        tenant_id = payload.get("tenant_id")
        if tenant_id is not None and not db_pg.get_tenant(tenant_id):
            return False
        set_context(
            user_id=user_id,
            tenant_id=tenant_id,
            role=payload.get("role", "user"),
            impersonating=bool(payload.get("imp")),
        )
        m._try_legacy_unlock()
        return True

    pin = (ws.query_params.get("pin") or "").strip()
    return m._ws_pin_ok(pin)


@router.get("/api/health")
async def health(request: Request):
    import main as m

    import time

    from app import auth_rate_limit, db_pg

    try:
        if m._is_server_mode():
            db_ok = db_pg.ping()
        else:
            with m._conn() as c:
                c.execute("SELECT 1").fetchone()
            db_ok = True
    except Exception:
        db_ok = False

    token = request.headers.get("Authorization", "")
    if not token:
        token = request.cookies.get("max_token", "")
    if not token.strip():
        vs = m.vault_status()
        return {
            "ok": db_ok and (vs["unlocked"] or vs["needs_setup"] or vs["legacy"]),
            "db_ok": db_ok,
        }

    started = getattr(m, "_app_started_at", None)
    uptime = time.time() - started if started else 0.0
    pg_latency = db_pg.ping_latency_ms() if m._is_server_mode() else None
    redis_ok = None
    if m.REDIS_URL:
        redis_ok = auth_rate_limit._get_redis() is not None
    expiring_7d = 0
    if m._is_server_mode():
        try:
            expiring_7d = db_pg.count_subscriptions_expiring(7)
        except Exception:
            expiring_7d = -1

    vs = m.vault_status()
    return {
        "ok": db_ok and (vs["unlocked"] or vs["needs_setup"] or vs["legacy"]),
        "db_ok": db_ok,
        "pg_latency_ms": pg_latency,
        "redis_ok": redis_ok,
        "server_mode": m._is_server_mode(),
        "worker_running": m.RUNTIME.worker_busy(),
        "worker_pool_size": m._pool_size(),
        "db_backend": m.DB_BACKEND,
        "redis_configured": bool(m.REDIS_URL),
        "celery_enabled": m.USE_CELERY,
        "subscriptions_expiring_7d": expiring_7d,
        "uptime_seconds": round(uptime, 1),
        "vault": vs,
        "circuit_open": m._circuit_open_count(),
        "version": m.APP_VERSION,
    }


@router.get("/metrics")
async def prometheus_metrics():
    import main as m
    import time

    from app import auth_rate_limit, db_pg

    started = getattr(m, "_app_started_at", None)
    uptime = time.time() - started if started else 0.0
    pg_up = 1 if (not m._is_server_mode() or db_pg.ping()) else 0
    redis_up = 0
    if m.REDIS_URL:
        redis_up = 1 if auth_rate_limit._get_redis() is not None else 0
    expiring = 0
    if m._is_server_mode():
        try:
            expiring = db_pg.count_subscriptions_expiring(7)
        except Exception:
            expiring = 0

    lines = [
        "# HELP max_sender_info Build info",
        "# TYPE max_sender_info gauge",
        f'max_sender_info{{version="{m.APP_VERSION}",db="{m.DB_BACKEND}"}} 1',
        "# HELP max_sender_uptime_seconds Process uptime",
        "# TYPE max_sender_uptime_seconds gauge",
        f"max_sender_uptime_seconds {uptime:.1f}",
        "# HELP max_sender_pg_up PostgreSQL reachable",
        "# TYPE max_sender_pg_up gauge",
        f"max_sender_pg_up {pg_up}",
        "# HELP max_sender_redis_up Redis reachable when configured",
        "# TYPE max_sender_redis_up gauge",
        f"max_sender_redis_up {redis_up}",
        "# HELP max_sender_subscriptions_expiring_7d Subscriptions expiring within 7 days",
        "# TYPE max_sender_subscriptions_expiring_7d gauge",
        f"max_sender_subscriptions_expiring_7d {expiring}",
        "# HELP max_sender_messages_sent_total Sent messages",
        "# TYPE max_sender_messages_sent_total counter",
        f"max_sender_messages_sent_total {m._metrics.get('messages_sent_total', 0):.0f}",
        "# HELP max_sender_messages_failed_total Failed messages",
        "# TYPE max_sender_messages_failed_total counter",
        f"max_sender_messages_failed_total {m._metrics.get('messages_failed_total', 0):.0f}",
        "# HELP max_sender_campaigns_started_total Campaigns started",
        "# TYPE max_sender_campaigns_started_total counter",
        f"max_sender_campaigns_started_total {m._metrics.get('campaigns_started_total', 0):.0f}",
        "# HELP max_sender_campaigns_finished_total Campaigns finished",
        "# TYPE max_sender_campaigns_finished_total counter",
        f"max_sender_campaigns_finished_total {m._metrics.get('campaigns_finished_total', 0):.0f}",
        "# HELP max_sender_worker_running Worker running flag",
        "# TYPE max_sender_worker_running gauge",
        f"max_sender_worker_running {1 if m.RUNTIME.worker_busy() else 0}",
        "# HELP max_sender_worker_pool_size Configured pool size",
        "# TYPE max_sender_worker_pool_size gauge",
        f"max_sender_worker_pool_size {m._pool_size()}",
        "# HELP max_sender_circuit_open Profiles in circuit breaker",
        "# TYPE max_sender_circuit_open gauge",
        f"max_sender_circuit_open {m._circuit_open_count()}",
        "# HELP max_sender_backups_total DB backups created",
        "# TYPE max_sender_backups_total counter",
        f"max_sender_backups_total {m._metrics.get('backups_total', 0):.0f}",
    ]
    body = "\n".join(lines) + "\n"
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")


@router.get("/api/status")
async def status():
    import main as m

    return m._build_status_payload()


@router.websocket("/ws/status")
async def ws_status(ws: WebSocket):
    """Пуш статуса ~1/с. Server: ?token=JWT. Local: ?pin=…"""
    import main as m

    from app.config import is_server_mode
    from app.tenant import clear_context

    if not _authenticate_ws(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        while not m.RUNTIME.shutting_down:
            await ws.send_json(m._build_status_payload())
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass
    except Exception:
        with contextlib.suppress(Exception):
            await ws.close()
    finally:
        if is_server_mode():
            clear_context()
