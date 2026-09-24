"""Panel API — groups."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException

import antiban_core
from app.routes_models import (
    BulkProfilesIn,
    DestinationVerifyIn,
    GroupIn,
    GroupPatchIn,
    ProfileIn,
)
from app.runtime import main as m
from app.services.errors import classify_exception
from app.tenant import is_cabinet_user, redact_cabinet_row

router = APIRouter(tags=["groups"])

_CABINET_DENIED = "Недоступно в личном кабинете"


def _safe_group_view(row: dict) -> dict:
    """Never expose proxy credentials through group APIs."""
    result = redact_cabinet_row(dict(row))
    raw_proxy = str(result.pop("proxy", "") or "")
    labels = []
    for proxy in antiban_core.parse_proxy_list(raw_proxy):
        try:
            parsed = urlsplit(proxy)
            host = parsed.hostname
            if not host:
                continue
            label = host
            if parsed.port:
                label += f":{parsed.port}"
            if label not in labels:
                labels.append(label)
        except ValueError:
            continue
    result["proxy_labels"] = labels
    return result


def _phone_or_400(raw: str) -> str:
    try:
        return m._normalize_phone(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _delete_orphan_profile(c, profile_id: int) -> bool:
    """Finalize an orphan profile only after its runtime has been drained."""
    linked = c.execute(
        "SELECT 1 FROM group_profiles WHERE profile_id=? LIMIT 1", (profile_id,)
    ).fetchone()
    if linked:
        return False
    c.execute("DELETE FROM antiban_state WHERE profile_id=?", (profile_id,))
    c.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
    return True


def _unselect_removed_work_group(c, profile_id: int, group_id: int) -> bool:
    """Fence a selected work group when its legacy association is removed."""
    table = c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='profile_automation_scope'"
    ).fetchone()
    if table is None:
        return False
    row = c.execute(
        "SELECT automation_group_id FROM profile_automation_scope WHERE profile_id=?",
        (int(profile_id),),
    ).fetchone()
    if row is None or row["automation_group_id"] != int(group_id):
        return False
    c.execute(
        "UPDATE profile_automation_scope SET automation_group_id=NULL, "
        "consent_state='unselected', revision=revision+1 WHERE profile_id=?",
        (int(profile_id),),
    )
    return True


def _cancel_queued_profile_slots(
    c, profile_id: int, *, group_id: int | None, reason: str
) -> int:
    """Cancel only queued daily slots pinned to a removed work association."""
    tables = {
        str(row["name"])
        for row in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('profile_daily_plans', 'profile_message_slots')"
        ).fetchall()
    }
    if tables != {"profile_daily_plans", "profile_message_slots"}:
        return 0
    group_clause = "" if group_id is None else " AND work_group_id=?"
    params: list[object] = [str(reason)[:500], int(profile_id)]
    if group_id is not None:
        params.append(int(group_id))
    cursor = c.execute(
        "UPDATE profile_message_slots SET status='cancelled', "
        "failure_reason=?, updated_at=datetime('now') "
        "WHERE status='queued' AND plan_id IN ("
        "SELECT plan_id FROM profile_daily_plans "
        "WHERE profile_id=? AND status='active'" + group_clause + ")",
        params,
    )
    return int(cursor.rowcount or 0)


async def _cleanup_profile_runtime(profile_id: int) -> None:
    """Drain all profile operations before removing the session runtime."""
    try:
        await m._delete_profile_runtime(profile_id)
    except Exception as exc:
        raise HTTPException(409, "PROFILE_RUNTIME_CLEANUP_FAILED") from exc


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
    return [_safe_group_view(dict(r)) for r in rows]


@router.get("/api/groups/{group_id}/profiles")
async def list_group_profiles(
    group_id: int,
    offset: int = 0,
    limit: int = 20,
    phone: str | None = None,
):

    phone_filter = _phone_or_400(phone) if (phone or "").strip() else None
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
    items = [m._profile_auth_view(p, group_id=int(group_id)) for p in rows]
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.post("/api/groups")
async def add_group(body: GroupIn):

    m._require_worker_idle()
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

    m._require_worker_idle()
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
                "UPDATE groups SET invite_link=?, max_chat_id='', "
                "destination_verified=0, destination_revision=destination_revision+1 "
                "WHERE id=?",
                (link, group_id),
            )
        if "proxy" in data:
            proxy = str(data["proxy"] or "").strip()
            from app.repositories.weekly_schedule import WeeklyScheduleRepository

            WeeklyScheduleRepository(c).update_group_proxy_list(int(group_id), proxy)
            m.append_log(
                f"Прокси группы #{group_id}: {'задан' if proxy else 'очищен'}"
            )
        if "is_active" in data and data["is_active"] is not None:
            c.execute(
                "UPDATE groups SET is_active=? WHERE id=?",
                (int(data["is_active"]), group_id),
            )
        row = c.execute("SELECT * FROM groups WHERE id=?", (group_id,)).fetchone()
    return _safe_group_view(dict(row))


@router.post("/api/groups/{group_id}/destination/verify")
async def verify_group_destination(group_id: int, body: DestinationVerifyIn):
    """Persist an explicit owner confirmation for the current link revision."""
    m._require_worker_idle()
    from app.repositories.automation_scope import (
        AutomationScopeError,
        AutomationScopeRepository,
    )

    with m._conn() as c:
        row = c.execute(
            "SELECT invite_link FROM groups WHERE id=?", (int(group_id),)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Группа не найдена")
        if not str(row["invite_link"] or "").strip():
            raise HTTPException(409, "DESTINATION_REVIEW_REQUIRED")
        try:
            AutomationScopeRepository(c).verify_destination(
                int(group_id),
                body.chat_id,
                expected_revision=body.revision,
            )
        except AutomationScopeError as exc:
            status = 404 if exc.code == "OBJECT_NOT_FOUND" else 409
            raise HTTPException(status, exc.code) from exc
        confirmed = c.execute(
            "SELECT * FROM groups WHERE id=?", (int(group_id),)
        ).fetchone()
    return _safe_group_view(dict(confirmed))


@router.post("/api/groups/{group_id}/profiles")
async def add_group_profile(group_id: int, body: ProfileIn):

    m._require_worker_idle()
    phone = _phone_or_400(body.phone)
    if is_cabinet_user() and (body.proxy or "").strip():
        raise HTTPException(403, _CABINET_DENIED)
    if (body.proxy or "").strip():
        raise HTTPException(400, "PROXY_ASSIGNMENT_AUTOMATIC")
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
                "INSERT INTO profiles (phone, label, status) VALUES (?, ?, ?)",
                (
                    phone,
                    body.label.strip(),
                    m.ProfileStatus.PENDING,
                ),
            )
            pid = cur.lastrowid

        n = c.execute(
            "SELECT COALESCE(MAX(order_index), -1) n FROM group_profiles WHERE group_id=?",
            (group_id,),
        ).fetchone()["n"]
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, order_index) VALUES (?, ?, ?)",
            (group_id, pid, n + 1),
        )
        from app.repositories.weekly_schedule import WeeklyScheduleRepository

        WeeklyScheduleRepository(c).assign_profile(int(pid), int(group_id))

    m._ensure_auth_session(pid)
    m.append_log(f"Профиль {phone} добавлен в группу #{group_id}")
    return {"id": pid, "phone": phone, "group_id": group_id}


@router.post("/api/groups/{group_id}/profiles/bulk")
async def bulk_add_group_profiles(group_id: int, body: BulkProfilesIn):

    """Импорт phone,label. Пропускает уже существующие в группе."""
    m._require_worker_idle()
    if is_cabinet_user():
        raise HTTPException(403, _CABINET_DENIED)
    if any((item.proxy or "").strip() for item in body.profiles):
        raise HTTPException(400, "PROXY_ASSIGNMENT_AUTOMATIC")
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
                        "INSERT INTO profiles (phone, label, status) VALUES (?, ?, ?)",
                        (
                            phone,
                            (item.label or "").strip(),
                            m.ProfileStatus.PENDING,
                        ),
                    )
                    pid = cur.lastrowid
                order_n += 1
                c.execute(
                    "INSERT INTO group_profiles (group_id, profile_id, order_index) "
                    "VALUES (?, ?, ?)",
                    (group_id, pid, order_n),
                )
                from app.repositories.weekly_schedule import WeeklyScheduleRepository

                WeeklyScheduleRepository(c).assign_profile(int(pid), int(group_id))
                added.append({"id": pid, "phone": phone})
            except Exception as e:
                info = classify_exception(
                    e, source="unknown", stage="profile_import", outcome="rejected"
                )
                errors.append(
                    {
                        "phone": getattr(item, "phone", "?"),
                        "error": info.safe_message,
                        "code": info.code,
                        "source": info.source,
                        "stage": info.stage,
                        "recommended_action": info.recommended_action,
                    }
                )

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

    m._require_worker_idle()
    orphan_profiles: list[int] = []
    with m._conn() as c:
        if not c.execute("SELECT 1 FROM groups WHERE id=?", (group_id,)).fetchone():
            raise HTTPException(404, "Группа не найдена")
        pids = [
            r["profile_id"]
            for r in c.execute(
                "SELECT profile_id FROM group_profiles WHERE group_id=?", (group_id,)
            ).fetchall()
        ]
        selected_profiles = {
            int(pid)
            for pid in pids
            if _unselect_removed_work_group(c, int(pid), int(group_id))
        }
        for pid in pids:
            _cancel_queued_profile_slots(
                c,
                int(pid),
                group_id=None if int(pid) in selected_profiles else int(group_id),
                reason="WORK_GROUP_UNLINKED",
            )
        c.execute("DELETE FROM group_profiles WHERE group_id=?", (group_id,))
        c.execute("DELETE FROM groups WHERE id=?", (group_id,))
        orphan_profiles = [
            pid
            for pid in pids
            if not c.execute(
                "SELECT 1 FROM group_profiles WHERE profile_id=? LIMIT 1", (pid,)
            ).fetchone()
        ]
    for pid in orphan_profiles:
        await _cleanup_profile_runtime(pid)
        try:
            m._release_automation_identity(pid)
        except Exception as exc:
            raise HTTPException(409, "SESSION_DELETE_FAILED") from exc
        with m._conn() as c:
            _delete_orphan_profile(c, pid)
    m.append_log(f"Группа #{group_id} удалена")
    return {"ok": True}


@router.delete("/api/groups/{group_id}/profiles/{profile_id}")
async def remove_group_profile(group_id: int, profile_id: int):

    m._require_worker_idle()
    orphan_profile = False
    with m._conn() as c:
        row = c.execute(
            "SELECT 1 FROM group_profiles WHERE group_id=? AND profile_id=?",
            (group_id, profile_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Профиль не в этой группе")
        selected_removed = _unselect_removed_work_group(c, profile_id, group_id)
        _cancel_queued_profile_slots(
            c,
            profile_id,
            group_id=None if selected_removed else group_id,
            reason="WORK_GROUP_UNLINKED",
        )
        c.execute(
            "DELETE FROM group_profiles WHERE group_id=? AND profile_id=?",
            (group_id, profile_id),
        )
        orphan_profile = not c.execute(
            "SELECT 1 FROM group_profiles WHERE profile_id=? LIMIT 1", (profile_id,)
        ).fetchone()
    if orphan_profile:
        await _cleanup_profile_runtime(profile_id)
        try:
            m._release_automation_identity(profile_id)
        except Exception as exc:
            raise HTTPException(409, "SESSION_DELETE_FAILED") from exc
        with m._conn() as c:
            _delete_orphan_profile(c, profile_id)
    m.append_log(f"Профиль #{profile_id} удалён из группы #{group_id}")
    return {"ok": True}
