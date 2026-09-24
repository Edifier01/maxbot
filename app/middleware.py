"""Middleware аутентификации для серверного режима."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import os
import time
import json
import logging
import uuid
from urllib.parse import urlsplit

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app import auth_rate_limit, db_pg
from app.auth import cached_validate_token_session, decode_token
from app.config import INTERNAL_SERVICE_TOKEN, is_server_mode
from app.runtime import main as app_main
from app.tenant import clear_context, set_context


access_logger = logging.getLogger("maxsender.access")


class UvicornInvitePathRedactor(logging.Filter):
    """Keep Uvicorn access auditing while redacting invite bearer tokens."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 4:
            path = str(args[2])
            if path.startswith("/join/"):
                record.args = (*args[:2], "/join/[redacted]", *args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(UvicornInvitePathRedactor())


async def _send_ingress_error(send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class IngressLimitsMiddleware:
    """Bound HTTP bodies and slow request uploads before route parsing."""

    def __init__(self, app, max_bytes: int | None = None, timeout: float | None = None):
        self.app = app
        self.max_bytes = max_bytes or app_main.MAX_HTTP_BODY_BYTES
        self.timeout = timeout or app_main.MAX_HTTP_BODY_TIMEOUT_SEC

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.lower(): value for key, value in scope.get("headers", [])
        }
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                declared_length = int(raw_length)
            except (TypeError, ValueError):
                await _send_ingress_error(send, 400, "Некорректный Content-Length")
                return
            if declared_length < 0:
                await _send_ingress_error(send, 400, "Некорректный Content-Length")
                return
            if declared_length > self.max_bytes:
                await _send_ingress_error(send, 413, "Запрос слишком большой")
                return

        messages = []
        received = 0
        try:
            async with asyncio.timeout(self.timeout):
                while True:
                    message = await receive()
                    messages.append(message)
                    if message.get("type") == "http.disconnect":
                        break
                    if message.get("type") != "http.request":
                        break
                    received += len(message.get("body", b""))
                    if received > self.max_bytes:
                        await _send_ingress_error(send, 413, "Запрос слишком большой")
                        return
                    if not message.get("more_body", False):
                        break
        except (TimeoutError, asyncio.TimeoutError):
            await _send_ingress_error(send, 408, "Загрузка запроса превысила лимит времени")
            return

        async def replay_receive():
            if messages:
                return messages.pop(0)
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)


def _same_origin_request(request: Request) -> bool:
    origin = request.headers.get("Origin", "").strip()
    if not origin:
        return True
    host = request.headers.get("Host", "").strip()
    if not host:
        return False
    try:
        parsed = urlsplit(origin)
        origin_host = parsed.hostname
        origin_port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme not in {"http", "https"}
        or origin_host is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return False
    try:
        host_parts = urlsplit(f"//{host}")
        request_host = host_parts.hostname
        request_port = host_parts.port
    except ValueError:
        return False
    if (
        request_host is None
        or host_parts.username is not None
        or host_parts.password is not None
        or host_parts.path
        or host_parts.query
        or host_parts.fragment
    ):
        return False
    default_port = 443 if parsed.scheme == "https" else 80
    return (
        origin_host.casefold() == request_host.casefold()
        and (origin_port or default_port) == (request_port or default_port)
    )


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Emit a small, secret-free access record for every server request."""

    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            from app.services.errors import classify_exception

            error = classify_exception(
                exc,
                source="unknown",
                stage="request",
                request_id=request_id,
            )
            access_logger.error(
                json.dumps(
                    {
                        "event": "request_error",
                        "method": request.method,
                        "path": _safe_log_path(request.url.path),
                        "request_id": request_id,
                        "error_code": error.code,
                    }
                )
            )
            return JSONResponse(
                status_code=500,
                content=asdict(error),
                headers={"X-Request-ID": request_id},
            )
        response.headers["X-Request-ID"] = request_id
        access_logger.info(
            json.dumps(
                {
                    "event": "request",
                    "method": request.method,
                    "path": _safe_log_path(request.url.path),
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "request_id": request_id,
                }
            )
        )
        return response


def _safe_log_path(path: str) -> str:
    """Invite tokens are bearer credentials and must never enter access logs."""
    return "/join/[redacted]" if path.startswith("/join/") else path


class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    """Строгий лимит на login/register (защита от брутфорса)."""

    AUTH_POST_PATHS = frozenset({
        "/api/auth/login",
        "/api/auth/restore-session",
    })
    _counters = auth_rate_limit._memory  # ponytail: test/e2e compat alias

    async def dispatch(self, request: Request, call_next):
        if not is_server_mode():
            return await call_next(request)
        if request.method != "POST" or request.url.path not in self.AUTH_POST_PATHS:
            return await call_next(request)

        limit, window = auth_rate_limit.auth_rate_limit_config()
        ip = auth_rate_limit.client_ip(request)
        key = f"auth_rl:{ip}:{request.url.path}"
        allowed = await asyncio.to_thread(
            auth_rate_limit.check_auth_rate_limit, key, limit, window
        )
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Слишком много попыток входа. Попробуйте позже."},
            )
        return await call_next(request)


class ServerAuthMiddleware(BaseHTTPMiddleware):
    INTERNAL_POST_PATHS = frozenset({"/api/campaign/start", "/api/campaign/schedule"})
    SUBSCRIPTION_POST_PATHS = frozenset({
        "/api/campaign/start",
        "/api/campaign/schedule",
        "/api/campaign/retry_failed",
        "/api/campaign/test",
    })
    PUBLIC_PREFIXES = (
        "/static",
        "/api/health",
        "/api/public/onboarding/",
        "/join/",
        "/ws/",
    )
    PUBLIC_EXACT = {
        "/",
        "/auth.html",
        "/admin.html",
        "/favicon.ico",
        "/join",
        "/api/auth/login",
        "/api/auth/restore-session",
        "/api/auth/exit-impersonation",
    }
    USER_FORBIDDEN = (
        "/api/settings",
        "/api/messages",
        "/api/campaign/pause",
        "/api/campaign/reset",
        "/api/campaign/test",
        "/api/campaign/schedule",
        "/api/campaign/retry_failed",
    )
    # Админ без tenant_id: глобальные и auth/admin API (не tenant-scoped)
    ADMIN_GLOBAL_PREFIXES = (
        "/api/admin",
        "/api/auth/",
        "/api/settings",
        "/api/messages",
        "/api/vault/",
    )

    def _admin_global_path(self, path: str) -> bool:
        return any(path.startswith(p) for p in self.ADMIN_GLOBAL_PREFIXES)

    async def dispatch(self, request: Request, call_next):
        if not is_server_mode():
            return await call_next(request)

        path = request.url.path

        bearer = ""
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            bearer = auth[7:].strip()

        internal = INTERNAL_SERVICE_TOKEN
        service_bearer = bool(internal and bearer == internal)

        if path == "/metrics":
            if service_bearer:
                return await call_next(request)
            return JSONResponse(
                status_code=401,
                content={"detail": "Требуется service token"},
            )

        invite_parts = path.strip("/").split("/")
        owner_invite_mutation = (
            len(invite_parts) == 4
            and invite_parts[:2] == ["api", "groups"]
            and invite_parts[2].isdigit()
            and invite_parts[3] == "onboarding-invite"
        )
        unsafe_method = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        if unsafe_method and (
            not _same_origin_request(request)
            or (owner_invite_mutation and not request.headers.get("Origin"))
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": "Недопустимый Origin"},
            )

        if path in self.PUBLIC_EXACT or any(
            path.startswith(p) for p in self.PUBLIC_PREFIXES
        ):
            response = await call_next(request)
            if path == "/join" or path.startswith("/join/") or path.startswith("/api/public/onboarding/"):
                response.headers["Cache-Control"] = "no-store, private"
                response.headers["Pragma"] = "no-cache"
                response.headers["Referrer-Policy"] = "no-referrer"
            return response

        if (
            service_bearer
            and request.method == "POST"
            and path in self.INTERNAL_POST_PATHS
        ):
            if is_server_mode():
                raw_tid = request.headers.get("X-Tenant-Id", "").strip()
                if not raw_tid.isdigit():
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "X-Tenant-Id обязателен для service token"},
                    )
                tenant_id = int(raw_tid)
                if not await asyncio.to_thread(db_pg.get_tenant, tenant_id):
                    return JSONResponse(
                        status_code=404,
                        content={"detail": "Учреждение не найдено"},
                    )
                if (
                    path in self.SUBSCRIPTION_POST_PATHS
                    and not await asyncio.to_thread(db_pg.subscription_active, tenant_id)
                ):
                    return JSONResponse(
                        status_code=402,
                        content={"detail": "Подписка не активна"},
                    )
                set_context(role="admin", tenant_id=tenant_id, use_global_data=False)
            else:
                set_context(role="admin", use_global_data=True)
            try:
                app_main._try_legacy_unlock()
                return await call_next(request)
            finally:
                clear_context()

        token = request.cookies.get("max_token", "")
        if not token:
            return JSONResponse(status_code=401, content={"detail": "Требуется вход"})

        try:
            payload = decode_token(token)
        except jwt.PyJWTError:
            return JSONResponse(status_code=401, content={"detail": "Сессия истекла"})

        session_err = await asyncio.to_thread(cached_validate_token_session, payload)
        if session_err:
            return JSONResponse(status_code=401, content={"detail": session_err})

        user_id = int(payload["sub"])
        role = payload.get("role", "user")
        tenant_id = payload.get("tenant_id")
        impersonating = bool(payload.get("imp"))

        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            user_key = auth_rate_limit.user_rate_limit_key(user_id, tenant_id)
            allowed = await asyncio.to_thread(
                auth_rate_limit.check_auth_rate_limit, user_key, 60, 60.0
            )
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Слишком много запросов"},
                )

        if path.startswith("/api/admin"):
            if impersonating:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Недоступно в режиме impersonation"},
                )
            if role != "admin":
                return JSONResponse(status_code=403, content={"detail": "Только админ"})
            use_global = path.startswith("/api/admin/settings") or path.startswith(
                "/api/admin/messages"
            )
            set_context(
                user_id=user_id,
                tenant_id=tenant_id if not use_global else None,
                role=role,
                impersonating=impersonating,
                use_global_data=use_global,
            )
        else:
            if role == "admin" and not impersonating:
                if path.startswith(("/api/settings", "/api/messages")):
                    set_context(
                        user_id=user_id,
                        tenant_id=None,
                        role=role,
                        use_global_data=True,
                    )
                elif tenant_id is None:
                    if not self._admin_global_path(path):
                        return JSONResponse(
                            status_code=403,
                            content={
                                "detail": "Админ: используйте /admin.html или войдите в кабинет пользователя"
                            },
                        )
                    set_context(
                        user_id=user_id,
                        tenant_id=None,
                        role=role,
                        impersonating=impersonating,
                        use_global_data=path.startswith(
                            ("/api/settings", "/api/messages", "/api/vault/")
                        ),
                    )
                else:
                    set_context(
                        user_id=user_id,
                        tenant_id=tenant_id,
                        role=role,
                        impersonating=impersonating,
                    )
            else:
                set_context(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    role=role,
                    impersonating=impersonating,
                )

        try:
            app_main._try_legacy_unlock()

            if role == "user" and any(path.startswith(p) for p in self.USER_FORBIDDEN):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Недоступно в личном кабинете"},
                )

            if (
                path in self.SUBSCRIPTION_POST_PATHS
                and request.method == "POST"
                and role == "user"
                and tenant_id
                and not await asyncio.to_thread(db_pg.subscription_active, tenant_id)
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Подписка не активна. Обратитесь к администратору."},
                )

            return await call_next(request)
        finally:
            clear_context()
