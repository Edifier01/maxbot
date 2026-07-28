"""Регистрация серверных маршрутов и middleware на FastAPI app."""

from __future__ import annotations

from server.app.config import is_server_mode
from server.app.middleware import ServerAuthMiddleware
from server.app.routes_admin import router as admin_router
from server.app.routes_auth import router as auth_router


def register_server(app) -> None:
    if not is_server_mode():
        return
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.add_middleware(ServerAuthMiddleware)
