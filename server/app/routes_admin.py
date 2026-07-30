"""Admin API: пользователи, подписки, impersonation, proxy."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import auth, db_pg
from app.tenant import get_user_id, is_admin

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


@router.get("/subscriptions/expiring")
async def list_expiring(days: int = 7):
    _require_admin()
    days = max(1, min(days, 90))
    items = []
    for row in db_pg.list_expiring_subscriptions(within_days=days):
        exp = row["expires_at"]
        items.append(
            {
                "tenant_id": row["tenant_id"],
                "institution_name": row["institution_name"],
                "email": row["email"],
                "expires_at": exp.isoformat()
                if hasattr(exp, "isoformat")
                else str(exp),
                "days_left": int(row["days_left"] or 0),
            }
        )
    return {"items": items, "within_days": days}


@router.get("/users")
async def list_users():
    _require_admin()
    items = await asyncio.to_thread(db_pg.list_tenants_with_users)
    result = []
    for row in items:
        result.append(
            {
                "tenant_id": row["tenant_id"],
                "institution_name": row["institution_name"],
                "email": row["email"],
                "user_id": row["user_id"],
                "created_at": row["created_at"].isoformat()
                if hasattr(row["created_at"], "isoformat")
                else str(row["created_at"]),
                "subscription": db_pg.subscription_info_from_expires(
                    row.get("subscription_expires")
                ),
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


def _drop_tenant_sqlite(tenant_id: int) -> None:
    import main as app_main

    data_dir = app_main.ROOT / "data" / "tenants" / str(tenant_id)
    key = str(data_dir)
    with app_main._db_lock:
        conn = app_main._tenant_db_conns.pop(key, None)
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()
    if data_dir.is_dir():
        shutil.rmtree(data_dir, ignore_errors=True)


@router.delete("/users/{tenant_id}")
async def delete_user(tenant_id: int):
    _require_admin()
    tenant = db_pg.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(404, "Учреждение не найдено")
    if not db_pg.get_tenant_user(tenant_id):
        raise HTTPException(404, "Пользователь учреждения не найден")

    from app.campaign_runtime import REGISTRY
    from app.campaign_worker import stop_worker
    from app.tenant import tenant_scope

    rt = REGISTRY.worker_for(tenant_id)
    if rt.worker_task and not rt.worker_task.done():
        with tenant_scope(tenant_id=tenant_id, role="admin"):
            await stop_worker(
                finish_status="stopped",
                reason="Учреждение удалено",
                tenant_id=tenant_id,
            )

    if not db_pg.delete_tenant(tenant_id):
        raise HTTPException(404, "Учреждение не найдено")
    _drop_tenant_sqlite(tenant_id)
    return {"ok": True}


@router.post("/impersonate/{tenant_id}")
async def impersonate(tenant_id: int):
    admin_id = _require_admin()
    tenant = db_pg.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(404, "Учреждение не найдено")
    db_pg.log_impersonation(admin_id, tenant_id)

    import main as app_main

    from app.tenant_init import init_tenant_db

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
    from app.tenant_sqlite import tenant_conn

    with tenant_conn(tenant_id, use_global_data=False) as c:
        row = c.execute("SELECT id FROM groups WHERE id=?", (group_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Группа не найдена")
        c.execute("UPDATE groups SET proxy=? WHERE id=?", (body.proxy.strip(), group_id))
    return {"ok": True}


@router.get("/tenants/{tenant_id}/stats")
async def tenant_stats(tenant_id: int):
    _require_admin()
    from app.tenant_sqlite import tenant_conn

    with tenant_conn(tenant_id) as c:
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
