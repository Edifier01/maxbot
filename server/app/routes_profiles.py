"""Panel API — profiles."""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, HTTPException

from app.routes_models import CodeIn, ProfilePatchIn
from app.runtime import main as m

router = APIRouter(tags=["profiles"])


@router.get("/api/profiles")
async def list_profiles(offset: int = 0, limit: int = 50, q: str = ""):

    """Только профили, привязанные хотя бы к одной группе."""
    base = """
        FROM profiles p
        WHERE EXISTS (SELECT 1 FROM group_profiles gp WHERE gp.profile_id = p.id)
    """
    with m._conn() as c:
        if q:
            rows = c.execute(
                f"SELECT p.* {base} AND (p.phone LIKE ? OR p.label LIKE ?) "
                "ORDER BY p.id LIMIT ? OFFSET ?",
                (f"%{q}%", f"%{q}%", limit, offset),
            ).fetchall()
            total = c.execute(
                f"SELECT COUNT(*) n {base} AND (p.phone LIKE ? OR p.label LIKE ?)",
                (f"%{q}%", f"%{q}%"),
            ).fetchone()["n"]
        else:
            rows = c.execute(
                f"SELECT p.* {base} ORDER BY p.id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            total = c.execute(f"SELECT COUNT(*) n {base}").fetchone()["n"]
    return {"items": [dict(r) for r in rows], "total": total}


@router.get("/api/profiles/{profile_id}")
async def get_profile(profile_id: int):

    with m._conn() as c:
        p = c.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
    if not p:
        raise HTTPException(404, "Профиль не найден")
    return m._profile_auth_view(p)


@router.patch("/api/profiles/{profile_id}")
async def patch_profile(profile_id: int, body: ProfilePatchIn):

    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "Нечего обновлять")
    with m._conn() as c:
        p = c.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
        if not p:
            raise HTTPException(404, "Профиль не найден")
        if "label" in data:
            c.execute(
                "UPDATE profiles SET label=? WHERE id=?",
                (str(data["label"] or "").strip(), profile_id),
            )
        if "proxy" in data:
            proxy = str(data["proxy"] or "").strip()
            c.execute(
                "UPDATE profiles SET proxy=? WHERE id=?",
                (proxy, profile_id),
            )
            m.append_log(
                f"Прокси #{profile_id}: {'задан' if proxy else 'очищен'}"
            )
        p2 = c.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
    return m._profile_auth_view(p2)


@router.post("/api/profiles/{profile_id}/login/reset")
async def reset_login(profile_id: int):

    """Сброс зависшего входа и удаление сессии."""
    task = m._login_tasks.get(m._auth_session_key(profile_id))
    if task and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    m._clear_session(profile_id)
    sess = m._ensure_auth_session(profile_id)
    m._drain_queue(sess["sms_q"])
    m._drain_queue(sess["pwd_q"])
    m._set_auth_step(profile_id, "idle")
    with m._conn() as c:
        c.execute(
            "UPDATE profiles SET status=?, last_error='' WHERE id=?",
            (m.ProfileStatus.PENDING, profile_id),
        )
    return {"ok": True}


@router.post("/api/profiles/{profile_id}/login")
async def login_profile(
    profile_id: int, fresh: bool = False, group_id: int | None = None
):

    m._require_vault_unlocked()
    with m._conn() as c:
        p = c.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
    if not p:
        raise HTTPException(404, "Профиль не найден")
    if group_id is not None:
        with m._conn() as c:
            linked = c.execute(
                "SELECT 1 FROM group_profiles WHERE group_id=? AND profile_id=?",
                (group_id, profile_id),
            ).fetchone()
        if not linked:
            raise HTTPException(400, "Профиль не состоит в этой группе")

    task = m._login_tasks.get(m._auth_session_key(profile_id))
    if task and not task.done():
        sess = m._ensure_auth_session(profile_id)
        return {
            "ok": True,
            "message": "Вход уже выполняется",
            "auth_step": sess["step"],
            "auth_hint": sess.get("hint", ""),
        }

    sess = m._ensure_auth_session(profile_id)
    m._drain_queue(sess["sms_q"])
    m._drain_queue(sess["pwd_q"])
    m._set_auth_step(profile_id, "connecting")

    async def _login():
        try:
            me_id = None
            try:
                me_id = await m._login_max(
                    profile_id, p["phone"], fresh=fresh, group_id=group_id
                )
            except Exception:
                if not fresh:
                    m.append_log(f"Профиль #{profile_id}: сессия не подошла, повтор по SMS…")
                    me_id = await m._login_max(
                        profile_id, p["phone"], fresh=True, group_id=group_id
                    )
                else:
                    raise
            with m._conn() as c:
                c.execute(
                    "UPDATE profiles SET status=?, last_error='' WHERE id=?",
                    (m.ProfileStatus.ACTIVE, profile_id),
                )
            m._clear_cooldown(profile_id)
            m._set_auth_step(profile_id, "idle")
            m.append_log(f"Профиль #{profile_id} авторизован (id={me_id})")
        except Exception as e:
            err = str(e)
            with m._conn() as c:
                c.execute(
                    "UPDATE profiles SET status=?, last_error=? WHERE id=?",
                    (m.ProfileStatus.NEEDS_REAUTH, err, profile_id),
                )
            m._set_auth_step(profile_id, "error")
            m.append_log(f"Ошибка входа #{profile_id}: {err}")
        finally:
            if m._auth_sessions.get(m._auth_session_key(profile_id), {}).get("step") == "connecting":
                m._set_auth_step(profile_id, "idle")

    m._login_tasks[m._auth_session_key(profile_id)] = asyncio.create_task(_login())
    msg = (
        "Новый вход: дождитесь SMS → код → OK. Облачный пароль — если MAX запросит."
        if fresh
        else "Вход запущен. Если придёт SMS — введите код → OK."
    )
    return {"ok": True, "message": msg, "auth_step": "connecting"}


@router.post("/api/profiles/{profile_id}/sms")
async def submit_sms(profile_id: int, body: CodeIn):

    sess = m._auth_sessions.get(m._auth_session_key(profile_id))
    if not sess:
        raise HTTPException(404, "Сначала нажмите «Войти»")
    code = body.code.strip()
    if not code:
        raise HTTPException(400, "Введите SMS-код")
    await sess["sms_q"].put(code)
    m._set_auth_step(profile_id, "verifying_sms")
    return {"ok": True, "message": "Код отправлен"}


@router.post("/api/profiles/{profile_id}/password")
async def submit_password(profile_id: int, body: CodeIn):

    sess = m._auth_sessions.get(m._auth_session_key(profile_id))
    if not sess:
        raise HTTPException(404, "Сначала нажмите «Войти»")
    code = body.code.strip()
    if not code:
        raise HTTPException(400, "Введите облачный пароль")
    await sess["pwd_q"].put(code)
    m._set_auth_step(profile_id, "verifying_password")
    return {"ok": True}


@router.patch("/api/profiles/{profile_id}/disable")
async def disable_profile(profile_id: int):

    with m._conn() as c:
        c.execute(
            "UPDATE profiles SET status=? WHERE id=?",
            (m.ProfileStatus.DISABLED, profile_id),
        )
    return {"ok": True}


