"""Middleware аутентификации для серверного режима."""

from __future__ import annotations

import os
import time
import json
import logging
import uuid

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


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Emit a small, secret-free access record for every server request."""

    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            access_logger.exception(
                json.dumps(
                    {
                        "event": "request_error",
                        "method": request.method,
                        "path": request.url.path,
                        "request_id": request_id,
                    }
                )
            )
            raise
        response.headers["X-Request-ID"] = request_id
        access_logger.info(
            json.dumps(
                {
                    "event": "request",
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "request_id": request_id,
                }
            )
        )
        return response


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
        if not auth_rate_limit.check_auth_rate_limit(key, limit, window):
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
        "/ws/",
    )
    PUBLIC_EXACT = {
        "/",
        "/auth.html",
        "/admin.html",
        "/favicon.ico",
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

        if path in self.PUBLIC_EXACT or any(
            path.startswith(p) for p in self.PUBLIC_PREFIXES
        ):
            return await call_next(request)

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
                if not db_pg.get_tenant(tenant_id):
                    return JSONResponse(
                        status_code=404,
                        content={"detail": "Учреждение не найдено"},
                    )
                if (
                    path in self.SUBSCRIPTION_POST_PATHS
                    and not db_pg.subscription_active(tenant_id)
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

        session_err = cached_validate_token_session(payload)
        if session_err:
            return JSONResponse(status_code=401, content={"detail": session_err})

        user_id = int(payload["sub"])
        role = payload.get("role", "user")
        tenant_id = payload.get("tenant_id")
        impersonating = bool(payload.get("imp"))

        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            user_key = f"user_rl:{user_id}:{int(time.monotonic() // 60)}"
            if not auth_rate_limit.check_auth_rate_limit(user_key, 60, 60.0):
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
                and not db_pg.subscription_active(tenant_id)
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Подписка не активна. Обратитесь к администратору."},
                )

            return await call_next(request)
        finally:
            clear_context()
