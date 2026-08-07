"""Регистрация серверных маршрутов и middleware на FastAPI app."""

from __future__ import annotations

from app.config import is_server_mode
from app.middleware import AuthRateLimitMiddleware, ServerAuthMiddleware
from app.routes_admin import router as admin_router
from app.routes_auth import router as auth_router
from app.routes_campaign import router as campaign_router
from app.routes_dashboard import router as dashboard_router
from app.routes_groups import router as groups_router
from app.routes_messages import router as messages_router
from app.routes_monitor import router as monitor_router
from app.routes_pages import router as pages_router
from app.routes_profiles import router as profiles_router
from app.routes_settings import router as settings_router
from app.routes_vault import router as vault_router


def register_panel(app) -> None:
    """Panel API + pages (desktop и server)."""
    app.include_router(pages_router)
    app.include_router(monitor_router)
    app.include_router(vault_router)
    app.include_router(profiles_router)
    app.include_router(groups_router)
    app.include_router(messages_router)
    app.include_router(settings_router)
    app.include_router(campaign_router)
    app.include_router(dashboard_router)


def register_server(app) -> None:
    register_panel(app)
    if not is_server_mode():
        return
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.add_middleware(ServerAuthMiddleware)
    app.add_middleware(AuthRateLimitMiddleware)
