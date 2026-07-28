"""Middleware аутентификации для серверного режима."""

from __future__ import annotations

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from server.app import db_pg
from server.app.auth import decode_token
from server.app.config import is_server_mode
from server.app.tenant import clear_context, set_context


class ServerAuthMiddleware(BaseHTTPMiddleware):
    PUBLIC_PREFIXES = (
        "/static",
        "/api/health",
        "/metrics",
        "/ws/",
    )
    PUBLIC_EXACT = {
        "/",
        "/auth.html",
        "/admin.html",
        "/favicon.ico",
        "/api/auth/register",
        "/api/auth/login",
    }
    USER_WRITE_FORBIDDEN = (
        "/api/settings",
        "/api/messages",
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
        if path in self.PUBLIC_EXACT or any(
            path.startswith(p) for p in self.PUBLIC_PREFIXES
        ):
            return await call_next(request)

        token = ""
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
        if not token:
            token = request.cookies.get("max_token", "")

        if not token:
            return JSONResponse(status_code=401, content={"detail": "Требуется вход"})

        try:
            payload = decode_token(token)
        except jwt.PyJWTError:
            return JSONResponse(status_code=401, content={"detail": "Сессия истекла"})

        user_id = int(payload["sub"])
        role = payload.get("role", "user")
        tenant_id = payload.get("tenant_id")
        impersonating = bool(payload.get("imp"))

        if path.startswith("/api/admin"):
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
            import main as app_main

            app_main._refresh_data_paths()
            app_main._reset_db_conn()
            app_main._try_legacy_unlock()

            if role == "user" and request.method != "GET":
                if any(path.startswith(p) for p in self.USER_WRITE_FORBIDDEN):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Недоступно в личном кабинете"},
                    )

            if (
                path in ("/api/campaign/start", "/api/campaign/schedule")
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
