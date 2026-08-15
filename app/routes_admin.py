"""Admin API: пользователи, подписки, impersonation, proxy."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

import antiban_core
from app import auth, db_pg
from app.auth_cookies import set_admin_backup_cookie, set_auth_cookie
from app.tenant import get_user_id, is_admin, is_impersonating
from app.tenant_sqlite import tenant_conn
from app.runtime import main as app_main

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _bulk_set_groups_active(active: int) -> dict:
    """is_active для всех групп всех учреждений (admin bulk)."""
    active_val = 1 if active else 0
    tenants_processed = 0
    groups_updated = 0
    skipped: list[dict[str, object]] = []
    for row in db_pg.list_tenants_with_users():
        tid = int(row["tenant_id"])
        db_path = app_main.ROOT / "data" / "tenants" / str(tid) / "app.db"
        if not db_path.is_file():
            skipped.append({"tenant_id": tid, "reason": "no_db"})
            continue
        try:
            with tenant_conn(tid) as c:
                cur = c.execute("UPDATE groups SET is_active=?", (active_val,))
                groups_updated += int(cur.rowcount or 0)
            tenants_processed += 1
        except Exception as e:
            skipped.append({"tenant_id": tid, "reason": str(e)[:200]})
    verb = "включены" if active_val else "выключены"
    app_main.append_log(
        f"Админ: группы {verb} у {tenants_processed} учреждений "
        f"({groups_updated} групп)"
    )
    return {
        "ok": True,
        "is_active": active_val,
        "tenants_processed": tenants_processed,
        "groups_updated": groups_updated,
        "skipped": skipped,
    }


class SubscriptionIn(BaseModel):
    days: int = Field(ge=1, le=3650)


class ProxyIn(BaseModel):
    proxy: str = Field(max_length=500)

    @field_validator("proxy")
    @classmethod
    def validate_proxy(cls, v: str) -> str:
        return antiban_core.normalize_proxy_field(v)


class AdminTenantSettingsIn(BaseModel):
    worker_pool_size: int = Field(ge=1, le=32)


def _require_admin() -> int:
    if is_impersonating():
        raise HTTPException(403, "Недоступно в режиме impersonation")
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
    expires = db_pg.extend_subscription(tenant_id, body.days, admin_id)
    return {"ok": True, "expires_at": expires.isoformat()}


@router.post("/users/{tenant_id}/subscription/month")
async def grant_subscription_month(tenant_id: int):
    return await grant_subscription(tenant_id, SubscriptionIn(days=30))


@router.post("/users/{tenant_id}/subscription/revoke")
async def revoke_subscription(tenant_id: int):
    admin_id = _require_admin()
    tenant = db_pg.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(404, "Учреждение не найдено")
    expires = db_pg.revoke_subscription(tenant_id, admin_id)
    return {"ok": True, "active": False, "expires_at": expires.isoformat()}


def _drop_tenant_sqlite(tenant_id: int) -> None:
    from app import sqlite_backend

    data_dir = app_main.ROOT / "data" / "tenants" / str(tenant_id)
    key = str(data_dir)
    with sqlite_backend._db_lock:
        conn = sqlite_backend._tenant_db_conns.pop(key, None)
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

    from app.campaign_worker import stop_worker
    from app.tenant import tenant_scope

    orphan_path = app_main.ROOT / "data" / "tenants" / str(tenant_id)

    with tenant_scope(tenant_id=tenant_id, role="admin"):
        await stop_worker(
            finish_status="stopped",
            reason="Учреждение удалено",
            tenant_id=tenant_id,
        )

    db_pg.bump_tenant_token_version(tenant_id)
    auth.clear_session_cache()

    await asyncio.to_thread(_drop_tenant_sqlite, tenant_id)
    try:
        if not db_pg.delete_tenant(tenant_id):
            raise HTTPException(404, "Учреждение не найдено")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "delete_user: PG delete failed after SQLite drop tenant_id=%s orphan_path=%s",
            tenant_id,
            orphan_path,
        )
        raise HTTPException(
            500,
            "Учреждение частично удалено (файлы удалены, запись в БД осталась). "
            "Сообщите администратору.",
        ) from exc
    return {"ok": True}


@router.post("/impersonate/{tenant_id}")
async def impersonate(tenant_id: int, request: Request):
    admin_id = _require_admin()
    tenant = db_pg.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(404, "Учреждение не найдено")
    db_pg.log_impersonation(admin_id, tenant_id)

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
    data = {
        "token": token,
        "tenant_id": tenant_id,
        "institution_name": tenant["institution_name"],
        "email": user_row["email"] if user_row else None,
    }
    response = JSONResponse(content=data)
    set_auth_cookie(response, token, remember_me=False, request=request)
    admin_token = (request.cookies.get("max_token") or "").strip()
    if admin_token:
        set_admin_backup_cookie(response, admin_token, request=request)
    return response


@router.put("/tenants/{tenant_id}/groups/{group_id}/proxy")
async def set_group_proxy(tenant_id: int, group_id: int, body: ProxyIn):
    _require_admin()

    def _update() -> bool:
        with tenant_conn(tenant_id, use_global_data=False) as c:
            row = c.execute("SELECT id FROM groups WHERE id=?", (group_id,)).fetchone()
            if not row:
                return False
            c.execute("UPDATE groups SET proxy=? WHERE id=?", (body.proxy, group_id))
            return True

    if not await asyncio.to_thread(_update):
        raise HTTPException(404, "Группа не найдена")
    return {"ok": True}


def _tenant_stats_sync(tenant_id: int) -> dict:
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


@router.get("/tenants/{tenant_id}/stats")
async def tenant_stats(tenant_id: int):
    _require_admin()
    return await asyncio.to_thread(_tenant_stats_sync, tenant_id)


def _tenant_worker_pool_size_sync(tenant_id: int) -> int:
    from app.tenant import tenant_scope

    with tenant_scope(tenant_id=tenant_id, role="admin"):
        return app_main._pool_size()


def _set_tenant_worker_pool_size_sync(tenant_id: int, worker_pool_size: int) -> int:
    from app.tenant import tenant_scope

    with tenant_scope(tenant_id=tenant_id, role="admin"):
        old = app_main._pool_size()
        app_main.set_setting("worker_pool_size", str(worker_pool_size))
        return old


@router.get("/tenants/{tenant_id}/settings")
async def get_tenant_settings(tenant_id: int):
    _require_admin()
    if not db_pg.get_tenant(tenant_id):
        raise HTTPException(404, "Учреждение не найдено")
    size = await asyncio.to_thread(_tenant_worker_pool_size_sync, tenant_id)
    return {"worker_pool_size": size}


@router.put("/tenants/{tenant_id}/settings")
async def update_tenant_settings(tenant_id: int, body: AdminTenantSettingsIn):
    _require_admin()
    if not db_pg.get_tenant(tenant_id):
        raise HTTPException(404, "Учреждение не найдено")

    from app.campaign_runtime import REGISTRY
    from app.campaign_worker import start_worker, stop_worker
    from app.tenant import tenant_scope

    old_size = await asyncio.to_thread(
        _set_tenant_worker_pool_size_sync, tenant_id, body.worker_pool_size
    )
    worker_restarted = False
    rt = REGISTRY.worker_for(tenant_id)
    if (
        rt.worker_task
        and not rt.worker_task.done()
        and old_size != body.worker_pool_size
    ):
        with tenant_scope(tenant_id=tenant_id, role="admin"):
            await stop_worker(
                finish_status=None,
                reason="Изменён worker_pool_size",
                tenant_id=tenant_id,
            )
            await start_worker(record_campaign=False)
        worker_restarted = True
        app_main.append_log(
            f"Админ: worker_pool_size {old_size}→{body.worker_pool_size}, "
            f"воркер перезапущен (tenant {tenant_id})"
        )
    elif old_size != body.worker_pool_size:
        app_main.append_log(
            f"Админ: worker_pool_size {old_size}→{body.worker_pool_size} "
            f"(tenant {tenant_id})"
        )
    return {
        "ok": True,
        "worker_pool_size": body.worker_pool_size,
        "worker_restarted": worker_restarted,
    }


@router.post("/groups/activate-all")
async def activate_all_groups():
    _require_admin()
    return await asyncio.to_thread(_bulk_set_groups_active, 1)


@router.post("/groups/deactivate-all")
async def deactivate_all_groups():
    _require_admin()
    return await asyncio.to_thread(_bulk_set_groups_active, 0)
