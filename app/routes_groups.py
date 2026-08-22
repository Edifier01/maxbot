"""Panel API — groups."""

from __future__ import annotations

import shutil

from fastapi import APIRouter, HTTPException

from app.routes_models import BulkProfilesIn, GroupIn, GroupPatchIn, ProfileIn
from app.runtime import main as m
from app.tenant import is_cabinet_user, redact_cabinet_row

router = APIRouter(tags=["groups"])

_CABINET_DENIED = "Недоступно в личном кабинете"


def _delete_orphan_profile(c, profile_id: int) -> bool:
    """Delete a profile only when no group still references it.

    This runs in the caller's SQLite transaction so group membership and
    profile cleanup either commit together or roll back together.
    """
    linked = c.execute(
        "SELECT 1 FROM group_profiles WHERE profile_id=? LIMIT 1", (profile_id,)
    ).fetchone()
    if linked:
        return False
    c.execute("DELETE FROM antiban_state WHERE profile_id=?", (profile_id,))
    c.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
    return True


def _cleanup_profile_runtime(profile_id: int) -> None:
    """Best-effort cleanup after the database transaction has committed."""
    session_key = m._auth_session_key(profile_id)
    m._auth_sessions.pop(session_key, None)
    task = m._login_tasks.pop(session_key, None)
    if task and not task.done():
        task.cancel()
    session_dir = m._resolve_data_dir() / "sessions" / str(profile_id)
    shutil.rmtree(session_dir, ignore_errors=True)


@router.get("/api/groups")
async def list_groups():

    with m._conn() as c:
        rows = c.execute(
            """
            SELECT g.*,
                   COUNT(CASE WHEN gp.is_enabled=1 AND p.status=? THEN 1 END) AS active_count,
                   COUNT(CASE WHEN gp.is_enabled=1 THEN 1 END) AS profiles_count
            FROM groups g
            LEFT JOIN group_profiles gp ON gp.group_id = g.id
            LEFT JOIN profiles p ON p.id = gp.profile_id
            GROUP BY g.id
            ORDER BY g.id
            """,
            (m.ProfileStatus.ACTIVE,),
        ).fetchall()
    return [redact_cabinet_row(dict(r)) for r in rows]


@router.get("/api/groups/{group_id}/profiles")
async def list_group_profiles(
    group_id: int,
    offset: int = 0,
    limit: int = 20,
    phone: str | None = None,
):

    phone_filter = m._normalize_phone(phone) if (phone or "").strip() else None
    with m._conn() as c:
        if not c.execute("SELECT 1 FROM groups WHERE id=?", (group_id,)).fetchone():
            raise HTTPException(404, "Группа не найдена")
        if phone_filter:
            total = c.execute(
                """
                SELECT COUNT(*) n FROM group_profiles gp
                JOIN profiles p ON p.id = gp.profile_id
                WHERE gp.group_id=? AND gp.is_enabled=1 AND p.phone=?
                """,
                (group_id, phone_filter),
            ).fetchone()["n"]
            rows = c.execute(
                """
                SELECT p.*, gp.order_index FROM profiles p
                JOIN group_profiles gp ON gp.profile_id = p.id
                WHERE gp.group_id=? AND gp.is_enabled=1 AND p.phone=?
                ORDER BY gp.order_index, p.id
                """,
                (group_id, phone_filter),
            ).fetchall()
        else:
            total = c.execute(
                "SELECT COUNT(*) n FROM group_profiles WHERE group_id=? AND is_enabled=1",
                (group_id,),
            ).fetchone()["n"]
            rows = c.execute(
                """
                SELECT p.*, gp.order_index FROM profiles p
                JOIN group_profiles gp ON gp.profile_id = p.id
                WHERE gp.group_id=? AND gp.is_enabled=1
                ORDER BY gp.order_index, p.id
                LIMIT ? OFFSET ?
                """,
                (group_id, min(max(limit, 1), 100), max(offset, 0)),
            ).fetchall()
    items = [m._profile_auth_view(p) for p in rows]
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.post("/api/groups")
async def add_group(body: GroupIn):

    invite = (body.invite_link or "").strip()
    if not invite:
        raise HTTPException(400, "Укажите пригласительную ссылку группы")
    proxy = (body.proxy or "").strip()
    if is_cabinet_user():
        if proxy:
            raise HTTPException(403, _CABINET_DENIED)
        proxy = ""
    with m._conn() as c:
        cur = c.execute(
            "INSERT INTO groups (name, max_chat_id, invite_link, proxy) VALUES (?, ?, ?, ?)",
            (
                body.name,
                "",
                invite,
                proxy,
            ),
        )
        gid = cur.lastrowid
    return {"id": gid}


@router.patch("/api/groups/{group_id}")
async def patch_group(group_id: int, body: GroupPatchIn):

    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "Нечего обновлять")
    if is_cabinet_user() and ("proxy" in data or "is_active" in data):
        raise HTTPException(403, _CABINET_DENIED)
    if "max_chat_id" in data:
        data.pop("max_chat_id")
    with m._conn() as c:
        if not c.execute("SELECT 1 FROM groups WHERE id=?", (group_id,)).fetchone():
            raise HTTPException(404, "Группа не найдена")
        if "name" in data and data["name"] is not None:
            c.execute(
                "UPDATE groups SET name=? WHERE id=?",
                (str(data["name"]).strip(), group_id),
            )
        if "max_chat_id" in data:
            c.execute(
                "UPDATE groups SET max_chat_id=? WHERE id=?",
                (str(data["max_chat_id"] or "").strip(), group_id),
            )
        if "invite_link" in data:
            link = str(data["invite_link"] or "").strip()
            if not link:
                raise HTTPException(400, "Нельзя очистить пригласительную ссылку группы")
            c.execute(
                "UPDATE groups SET invite_link=? WHERE id=?",
                (link, group_id),
            )
        if "proxy" in data:
            proxy = str(data["proxy"] or "").strip()
            c.execute("UPDATE groups SET proxy=? WHERE id=?", (proxy, group_id))
            m.append_log(
                f"Прокси группы #{group_id}: {'задан' if proxy else 'очищен'}"
            )
        if "is_active" in data and data["is_active"] is not None:
            c.execute(
                "UPDATE groups SET is_active=? WHERE id=?",
                (int(data["is_active"]), group_id),
            )
        row = c.execute("SELECT * FROM groups WHERE id=?", (group_id,)).fetchone()
    return redact_cabinet_row(dict(row))


@router.post("/api/groups/{group_id}/profiles")
async def add_group_profile(group_id: int, body: ProfileIn):

    phone = m._normalize_phone(body.phone)
    if is_cabinet_user() and (body.proxy or "").strip():
        raise HTTPException(403, _CABINET_DENIED)
    with m._conn() as c:
        g = c.execute("SELECT id FROM groups WHERE id=?", (group_id,)).fetchone()
        if not g:
            raise HTTPException(404, "Группа не найдена")

        row = c.execute("SELECT * FROM profiles WHERE phone=?", (phone,)).fetchone()
        if row:
            pid = row["id"]
            linked = c.execute(
                "SELECT 1 FROM group_profiles WHERE group_id=? AND profile_id=?",
                (group_id, pid),
            ).fetchone()
            if linked:
                raise HTTPException(400, "Этот номер уже в группе")
        else:
            cur = c.execute(
                "INSERT INTO profiles (phone, label, status, proxy) VALUES (?, ?, ?, ?)",
                (
                    phone,
                    body.label.strip(),
                    m.ProfileStatus.PENDING,
                    (body.proxy or "").strip(),
                ),
            )
            pid = cur.lastrowid
        if body.proxy is not None and str(body.proxy).strip() != "":
            c.execute(
                "UPDATE profiles SET proxy=? WHERE id=?",
                (body.proxy.strip(), pid),
            )

        n = c.execute(
            "SELECT COALESCE(MAX(order_index), -1) n FROM group_profiles WHERE group_id=?",
            (group_id,),
        ).fetchone()["n"]
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, order_index) VALUES (?, ?, ?)",
            (group_id, pid, n + 1),
        )

    m._ensure_auth_session(pid)
    m.append_log(f"Профиль {phone} добавлен в группу #{group_id}")
    return {"id": pid, "phone": phone, "group_id": group_id}


@router.post("/api/groups/{group_id}/profiles/bulk")
async def bulk_add_group_profiles(group_id: int, body: BulkProfilesIn):

    """Импорт phone,label. Пропускает уже существующие в группе."""
    if is_cabinet_user():
        raise HTTPException(403, _CABINET_DENIED)
    if not body.profiles:
        raise HTTPException(400, "Список профилей пуст")
    if len(body.profiles) > 2000:
        raise HTTPException(400, "Максимум 2000 профилей за раз")

    added, skipped, errors = [], [], []
    with m._conn() as c:
        if not c.execute("SELECT id FROM groups WHERE id=?", (group_id,)).fetchone():
            raise HTTPException(404, "Группа не найдена")
        order_n = c.execute(
            "SELECT COALESCE(MAX(order_index), -1) n FROM group_profiles WHERE group_id=?",
            (group_id,),
        ).fetchone()["n"]

        for item in body.profiles:
            try:
                phone = m._normalize_phone(item.phone)
                if len(phone) < 8:
                    errors.append({"phone": item.phone, "error": "Некорректный номер"})
                    continue
                row = c.execute(
                    "SELECT * FROM profiles WHERE phone=?", (phone,)
                ).fetchone()
                if row:
                    pid = row["id"]
                    linked = c.execute(
                        "SELECT 1 FROM group_profiles WHERE group_id=? AND profile_id=?",
                        (group_id, pid),
                    ).fetchone()
                    if linked:
                        skipped.append(phone)
                        continue
                else:
                    cur = c.execute(
                        "INSERT INTO profiles (phone, label, status, proxy) VALUES (?, ?, ?, ?)",
                        (
                            phone,
                            (item.label or "").strip(),
                            m.ProfileStatus.PENDING,
                            (item.proxy or "").strip(),
                        ),
                    )
                    pid = cur.lastrowid
                if (item.proxy or "").strip():
                    c.execute(
                        "UPDATE profiles SET proxy=? WHERE id=?",
                        (item.proxy.strip(), pid),
                    )
                order_n += 1
                c.execute(
                    "INSERT INTO group_profiles (group_id, profile_id, order_index) "
                    "VALUES (?, ?, ?)",
                    (group_id, pid, order_n),
                )
                added.append({"id": pid, "phone": phone})
            except Exception as e:
                errors.append({"phone": getattr(item, "phone", "?"), "error": str(e)})

    for a in added:
        m._ensure_auth_session(a["id"])
    m.append_log(
        f"Массовый импорт в группу #{group_id}: +{len(added)}, пропуск {len(skipped)}, "
        f"ошибок {len(errors)}"
    )
    return {
        "added": len(added),
        "skipped": len(skipped),
        "errors": errors[:50],
        "items": added,
    }


@router.delete("/api/groups/{group_id}")
async def delete_group(group_id: int):

    deleted_profiles: list[int] = []
    with m._conn() as c:
        if not c.execute("SELECT 1 FROM groups WHERE id=?", (group_id,)).fetchone():
            raise HTTPException(404, "Группа не найдена")
        pids = [
            r["profile_id"]
            for r in c.execute(
                "SELECT profile_id FROM group_profiles WHERE group_id=?", (group_id,)
            ).fetchall()
        ]
        c.execute("DELETE FROM group_profiles WHERE group_id=?", (group_id,))
        c.execute("DELETE FROM groups WHERE id=?", (group_id,))
        deleted_profiles = [pid for pid in pids if _delete_orphan_profile(c, pid)]
    for pid in deleted_profiles:
        _cleanup_profile_runtime(pid)
    m.append_log(f"Группа #{group_id} удалена")
    return {"ok": True}


@router.delete("/api/groups/{group_id}/profiles/{profile_id}")
async def remove_group_profile(group_id: int, profile_id: int):

    deleted_profile = False
    with m._conn() as c:
        row = c.execute(
            "SELECT 1 FROM group_profiles WHERE group_id=? AND profile_id=?",
            (group_id, profile_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Профиль не в этой группе")
        c.execute(
            "DELETE FROM group_profiles WHERE group_id=? AND profile_id=?",
            (group_id, profile_id),
        )
        deleted_profile = _delete_orphan_profile(c, profile_id)
    if deleted_profile:
        _cleanup_profile_runtime(profile_id)
    m.append_log(f"Профиль #{profile_id} удалён из группы #{group_id}")
    return {"ok": True}


