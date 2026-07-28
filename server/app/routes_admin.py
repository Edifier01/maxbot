"""Admin API: пользователи, подписки, impersonation, proxy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.app import auth, db_pg
from server.app.tenant import get_user_id, is_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


class SubscriptionIn(BaseModel):
    days: int = Field(ge=1, le=3650)


class ProxyIn(BaseModel):
    proxy: str = Field(max_length=500)


def _require_admin() -> int:
    if not is_admin():
        raise HTTPException(403, "Только админ")
    uid = get_user_id()
    if uid is None:
        raise HTTPException(401, "Требуется вход")
    return uid


@router.get("/users")
async def list_users():
    _require_admin()
    items = db_pg.list_tenants_with_users()
    result = []
    for row in items:
        tid = row["tenant_id"]
        sub = db_pg.subscription_info(tid)
        result.append(
            {
                "tenant_id": tid,
                "institution_name": row["institution_name"],
                "email": row["email"],
                "user_id": row["user_id"],
                "created_at": row["created_at"].isoformat()
                if hasattr(row["created_at"], "isoformat")
                else str(row["created_at"]),
                "subscription": sub,
            }
        )
    return {"items": result}


@router.post("/users/{tenant_id}/subscription")
async def grant_subscription(tenant_id: int, body: SubscriptionIn):
    admin_id = _require_admin()
    tenant = db_pg.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(404, "Учреждение не найдено")
    expires = datetime.now(timezone.utc) + timedelta(days=body.days)
    db_pg.grant_subscription(tenant_id, expires, admin_id)
    return {"ok": True, "expires_at": expires.isoformat()}


@router.post("/users/{tenant_id}/subscription/month")
async def grant_subscription_month(tenant_id: int):
    return await grant_subscription(tenant_id, SubscriptionIn(days=30))


@router.post("/impersonate/{tenant_id}")
async def impersonate(tenant_id: int):
    admin_id = _require_admin()
    tenant = db_pg.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(404, "Учреждение не найдено")
    db_pg.log_impersonation(admin_id, tenant_id)

    import main as app_main

    from server.app.tenant_init import init_tenant_db

    init_tenant_db(app_main, tenant_id)

    user_row = None
    for row in db_pg.list_tenants_with_users():
        if row["tenant_id"] == tenant_id:
            user_row = row
            break
    token = auth.create_token(
        admin_id,
        tenant_id=tenant_id,
        role="admin",
        impersonating=True,
        impersonator_id=admin_id,
    )
    return {
        "token": token,
        "tenant_id": tenant_id,
        "institution_name": tenant["institution_name"],
        "email": user_row["email"] if user_row else None,
    }


@router.put("/tenants/{tenant_id}/groups/{group_id}/proxy")
async def set_group_proxy(tenant_id: int, group_id: int, body: ProxyIn):
    _require_admin()
    import main as app_main
    from server.app.tenant import set_context

    set_context(tenant_id=tenant_id, role="admin", use_global_data=False)
    app_main._refresh_data_paths()
    app_main._reset_db_conn()
    with app_main._conn() as c:
        row = c.execute("SELECT id FROM groups WHERE id=?", (group_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Группа не найдена")
        c.execute("UPDATE groups SET proxy=? WHERE id=?", (body.proxy.strip(), group_id))
    return {"ok": True}


@router.get("/tenants/{tenant_id}/stats")
async def tenant_stats(tenant_id: int):
    _require_admin()
    import main as app_main
    from server.app.tenant import set_context

    set_context(tenant_id=tenant_id, role="admin")
    app_main._refresh_data_paths()
    app_main._reset_db_conn()
    with app_main._conn() as c:
        profiles = c.execute("SELECT COUNT(*) AS n FROM profiles").fetchone()["n"]
        groups = c.execute("SELECT COUNT(*) AS n FROM groups").fetchone()["n"]
        sent = c.execute(
            "SELECT COUNT(*) AS n FROM send_log WHERE status='sent'"
        ).fetchone()["n"]
        failed = c.execute(
            "SELECT COUNT(*) AS n FROM send_log WHERE status='failed'"
        ).fetchone()["n"]
    return {
        "tenant_id": tenant_id,
        "profiles": profiles,
        "groups": groups,
        "sent": sent,
        "failed": failed,
        "subscription": db_pg.subscription_info(tenant_id),
    }
