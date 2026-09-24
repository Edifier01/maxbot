"""Panel API — profiles."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from app.routes_models import (
    AutomationScopeIn,
    AuthAttemptStartIn,
    AuthCodeIn,
    AuthPasswordIn,
    CodeIn,
    ProfilePatchIn,
    SessionDeleteIn,
)
from app.runtime import main as m
from app.services.errors import classify_exception, redact_error
from app.tenant import (
    clear_context,
    is_cabinet_user,
    redact_cabinet_row,
    restore_context,
    snapshot_context,
)

router = APIRouter(tags=["profiles"])

_CABINET_DENIED = "Недоступно в личном кабинете"


def _raise_auth_attempt_http(exc: Exception) -> None:
    from app.services.auth_attempts import AuthAttemptError

    if isinstance(exc, AuthAttemptError):
        raise HTTPException(exc.status_code, detail=exc.code) from exc
    raise exc


async def _cancel_login_task(profile_id: int) -> None:
    await m._cancel_login_task(profile_id)


def _reset_transient_auth_session(profile_id: int) -> None:
    sess = m._ensure_auth_session(profile_id)
    m._drain_queue(sess["sms_q"])
    m._drain_queue(sess["pwd_q"])
    sess.update(
        {
            "step": "idle",
            "hint": "",
            "attempt_id": None,
            "revision": 0,
            "stage_deadline_at": None,
            "attempt_deadline_at": None,
        }
    )


async def _run_login_attempt(
    profile_id: int,
    phone: str,
    *,
    fresh: bool,
    group_id: int | None,
) -> int:
    """Run exactly the user-selected login mode once."""
    return await m._login_max(profile_id, phone, fresh=fresh, group_id=group_id)


@router.get("/api/profiles")
async def list_profiles(offset: int = 0, limit: int = 50, q: str = ""):

    """Только профили, привязанные хотя бы к одной группе."""
    limit = min(max(int(limit), 1), 200)
    offset = max(int(offset), 0)
    q = (q or "")[:100]
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
    items = [
        redact_cabinet_row(m._sanitize_profile_error_view(dict(row)))
        for row in rows
    ]
    return {"items": items, "total": total}


@router.get("/api/profiles/{profile_id}")
async def get_profile(profile_id: int):

    with m._conn() as c:
        p = c.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
    if not p:
        raise HTTPException(404, "Профиль не найден")
    return m._profile_auth_view(p)


@router.put("/api/profiles/{profile_id}/automation-scope")
async def select_automation_scope(profile_id: int, body: AutomationScopeIn):
    """Select one linked work group without touching the MAX session."""
    m._require_worker_idle()
    from app.repositories.automation_scope import (
        AutomationScopeError,
        AutomationScopeRepository,
    )

    with m._conn() as c:
        if not c.execute(
            "SELECT 1 FROM profiles WHERE id=?", (int(profile_id),)
        ).fetchone():
            raise HTTPException(404, "Профиль не найден")
        repository = AutomationScopeRepository(c)
        try:
            repository.select_work_group(profile_id, body.group_id)
        except AutomationScopeError as exc:
            raise HTTPException(409, exc.code) from exc
        scope = repository.scope_for(profile_id)
    return {
        "ok": True,
        "profile_id": int(profile_id),
        "automation_group_id": int(scope["automation_group_id"]),
        "consent_state": str(scope["consent_state"]),
        "revision": int(scope["revision"]),
        "session_preserved": True,
    }


@router.post("/api/profiles/{profile_id}/auth-attempts")
async def start_auth_attempt(profile_id: int, body: AuthAttemptStartIn):
    """Canonical guarded auth start; the legacy login route delegates here."""
    return await login_profile(
        profile_id,
        fresh=body.mode == "login",
        group_id=body.group_id,
        request_id=body.request_id,
    )


@router.get("/api/profiles/{profile_id}/auth-attempts/{attempt_id}")
async def get_auth_attempt(profile_id: int, attempt_id: str):
    try:
        view = m._auth_attempts().get(
            m._auth_attempt_scope(), profile_id, attempt_id
        )
    except Exception as exc:
        from app.services.auth_attempts import AuthAttemptError, AuthAttemptNotFound

        if not isinstance(exc, AuthAttemptNotFound):
            _raise_auth_attempt_http(exc)
        persisted = m._persisted_auth_attempt_public(profile_id, attempt_id)
        if persisted is None:
            _raise_auth_attempt_http(
                exc if isinstance(exc, AuthAttemptError) else RuntimeError("attempt_not_found")
            )
        return {"ok": True, "profile_id": profile_id, **persisted}
    return {"ok": True, "profile_id": profile_id, **view.public()}


@router.post("/api/profiles/{profile_id}/auth-attempts/{attempt_id}/code")
async def submit_auth_attempt_code(
    profile_id: int, attempt_id: str, body: AuthCodeIn
):
    sess = m._auth_sessions.get(m._auth_session_key(profile_id))
    if not sess:
        raise HTTPException(409, "attempt_runtime_unavailable")
    try:
        view, accepted = m._submit_auth_code_once(
            profile_id,
            attempt_id=attempt_id,
            revision=body.revision,
            request_id=body.request_id,
        )
    except Exception as exc:
        _raise_auth_attempt_http(exc)
        raise AssertionError("unreachable")
    if accepted:
        await sess["sms_q"].put(body.code)
    return {"ok": True, **view.public()}


@router.post("/api/profiles/{profile_id}/auth-attempts/{attempt_id}/password")
async def submit_auth_attempt_password(
    profile_id: int, attempt_id: str, body: AuthPasswordIn
):
    if not body.password or not body.password.strip():
        raise HTTPException(400, "Введите облачный пароль")
    sess = m._auth_sessions.get(m._auth_session_key(profile_id))
    if not sess:
        raise HTTPException(409, "attempt_runtime_unavailable")
    try:
        view, accepted = m._submit_auth_password_once(
            profile_id,
            attempt_id=attempt_id,
            revision=body.revision,
            request_id=body.request_id,
        )
    except Exception as exc:
        _raise_auth_attempt_http(exc)
        raise AssertionError("unreachable")
    if accepted:
        await sess["pwd_q"].put(body.password)
    return {"ok": True, **view.public()}


@router.post("/api/profiles/{profile_id}/auth-attempts/{attempt_id}/cancel")
async def cancel_auth_attempt(profile_id: int, attempt_id: str):
    current = m._current_auth_attempt(profile_id)
    try:
        view = m._cancel_auth_attempt_for_id(profile_id, attempt_id=attempt_id)
    except Exception as exc:
        _raise_auth_attempt_http(exc)
        raise AssertionError("unreachable")
    if view is None:
        raise HTTPException(404, "attempt_not_found")
    if current is not None and current.attempt_id == view.attempt_id:
        await _cancel_login_task(profile_id)
    return {"ok": True, **view.public(), "session_preserved": True}


@router.patch("/api/profiles/{profile_id}")
async def patch_profile(profile_id: int, body: ProfilePatchIn):

    m._require_worker_idle()
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "Нечего обновлять")
    if is_cabinet_user() and "proxy" in data:
        raise HTTPException(403, _CABINET_DENIED)
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

    """Cancel the current attempt without deleting the long-lived session."""
    m._require_worker_idle()
    m._cancel_auth_attempt(profile_id)
    await _cancel_login_task(profile_id)
    _reset_transient_auth_session(profile_id)
    return {
        "ok": True,
        "message": "Текущий вход отменён; сохранённая сессия не удалена",
        "session_preserved": True,
    }


@router.post("/api/profiles/{profile_id}/session/delete")
async def delete_profile_session(profile_id: int, body: SessionDeleteIn):
    """Explicitly delete a profile's long-lived MAX session runtime."""
    if getattr(body, "confirm", None) != "DELETE_SESSION":
        raise HTTPException(422, "Подтвердите удаление сессии")
    m._require_worker_idle()
    m._require_vault_unlocked()
    with m._conn() as c:
        if not c.execute("SELECT 1 FROM profiles WHERE id=?", (profile_id,)).fetchone():
            raise HTTPException(404, "Профиль не найден")

    m._cancel_auth_attempt(profile_id)
    try:
        await m._delete_profile_runtime(profile_id)
    except Exception as exc:
        raise HTTPException(409, "SESSION_DELETE_FAILED") from exc
    try:
        m._release_automation_identity(profile_id)
    except Exception as exc:
        raise HTTPException(409, "SESSION_DELETE_FAILED") from exc
    with m._conn() as c:
        c.execute(
            "UPDATE profiles SET status=?, last_error='' WHERE id=?",
            (m.ProfileStatus.PENDING, profile_id),
        )
    return {
        "ok": True,
        "message": "Сессия профиля удалена; потребуется новый вход",
        "session_deleted": True,
    }


@router.post("/api/profiles/{profile_id}/login")
async def login_profile(
    profile_id: int,
    fresh: bool = False,
    group_id: int | None = None,
    request_id: str | None = None,
):

    m._require_worker_idle()
    m._require_profile_runtime_available(profile_id)
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
        if not m._automation_scope_allows_external_action(profile_id, group_id):
            raise HTTPException(409, "WORK_GROUP_SELECTION_REQUIRED")

    task = m._login_tasks.get(m._auth_session_key(profile_id))
    current_attempt = m._current_auth_attempt(profile_id)
    if task and not task.done():
        if current_attempt is not None:
            return {
                "ok": True,
                "message": "Вход уже выполняется",
                **current_attempt.public(),
            }
        sess = m._ensure_auth_session(profile_id)
        return {
            "ok": True,
            "message": "Вход уже выполняется",
            "auth_step": sess["step"],
            "auth_hint": sess.get("hint", ""),
        }

    try:
        attempt, created = m._start_auth_attempt(
            profile_id,
            group_id=group_id,
            fresh=fresh,
            request_id=request_id,
        )
    except Exception as exc:
        _raise_auth_attempt_http(exc)
        raise AssertionError("unreachable")
    if not created:
        return {
            "ok": True,
            "message": "Вход уже выполняется",
            **attempt.public(),
        }

    sess = m._ensure_auth_session(profile_id)
    m._drain_queue(sess["sms_q"])
    m._drain_queue(sess["pwd_q"])
    m._set_auth_step(profile_id, "connecting")
    session_key = m._auth_session_key(profile_id)
    ctx_snap = snapshot_context() if m._is_server_mode() else None

    async def _login():
        if ctx_snap is not None:
            restore_context(ctx_snap)
        try:
            # A saved-session failure is not proof that its token is invalid.
            # Fresh login is an explicit user action (`fresh=true`) only.
            me_id = await _run_login_attempt(
                profile_id, p["phone"], fresh=fresh, group_id=group_id
            )
            m._claim_automation_identity(profile_id, me_id)
            with m._conn() as c:
                c.execute(
                    "UPDATE profiles SET status=?, last_error='' WHERE id=?",
                    (m.ProfileStatus.ACTIVE, profile_id),
                )
            m._clear_cooldown(profile_id)
            m._finish_auth_attempt(profile_id, success=True)
            m.append_log(f"Профиль #{profile_id} авторизован (id={me_id})")
        except Exception as e:
            info = redact_error(
                classify_exception(e, source="max", stage="login", outcome="rejected")
            )
            err = info.safe_message
            m._finish_auth_attempt(
                profile_id, success=False, error_code=info.code
            )
            if info.code == "MAX_ACCOUNT_BANNED":
                with m._conn() as c:
                    c.execute(
                        "UPDATE profiles SET status=?, last_error=? WHERE id=?",
                        (m.ProfileStatus.BANNED, err, profile_id),
                    )
                m._set_auth_step(profile_id, "error")
                m.append_log(f"Профиль #{profile_id} забанен при входе: {err}")
                await m._handle_profile_banned(profile_id, err)
            else:
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
            if ctx_snap is not None:
                clear_context()

    m._login_tasks[session_key] = asyncio.create_task(_login())
    msg = (
        "Новый вход: дождитесь SMS → код → OK. Облачный пароль — если MAX запросит."
        if fresh
        else "Вход запущен. Если придёт SMS — введите код → OK."
    )
    return {"ok": True, "message": msg, **attempt.public()}


@router.post("/api/profiles/{profile_id}/sms")
async def submit_sms(profile_id: int, body: CodeIn):

    m._require_worker_idle()
    sess = m._auth_sessions.get(m._auth_session_key(profile_id))
    if not sess:
        raise HTTPException(404, "Сначала нажмите «Войти»")
    code = body.code.strip()
    if not code:
        raise HTTPException(400, "Введите SMS-код")
    if not code.isascii() or not code.isdigit() or len(code) > 32:
        raise HTTPException(422, "OTP_FORMAT_INVALID")
    if not body.attempt_id or body.revision is None:
        raise HTTPException(409, "attempt_identity_required")
    try:
        view, accepted = m._submit_auth_code_once(
            profile_id,
            attempt_id=body.attempt_id,
            revision=body.revision,
            request_id=body.request_id,
        )
    except Exception as exc:
        _raise_auth_attempt_http(exc)
        raise AssertionError("unreachable")
    if accepted:
        await sess["sms_q"].put(code)
    return {"ok": True, "message": "Код отправлен", **view.public()}


@router.post("/api/profiles/{profile_id}/password")
async def submit_password(profile_id: int, body: CodeIn):

    m._require_worker_idle()
    sess = m._auth_sessions.get(m._auth_session_key(profile_id))
    if not sess:
        raise HTTPException(404, "Сначала нажмите «Войти»")
    code = body.code
    if not code or not code.strip():
        raise HTTPException(400, "Введите облачный пароль")
    if not body.attempt_id or body.revision is None:
        raise HTTPException(409, "attempt_identity_required")
    try:
        view, accepted = m._submit_auth_password_once(
            profile_id,
            attempt_id=body.attempt_id,
            revision=body.revision,
            request_id=body.request_id,
        )
    except Exception as exc:
        _raise_auth_attempt_http(exc)
        raise AssertionError("unreachable")
    if accepted:
        await sess["pwd_q"].put(code)
    return {"ok": True, **view.public()}


@router.patch("/api/profiles/{profile_id}/disable")
async def disable_profile(profile_id: int):

    m._require_worker_idle()
    with m._conn() as c:
        c.execute(
            "UPDATE profiles SET status=? WHERE id=?",
            (m.ProfileStatus.DISABLED, profile_id),
        )
    return {"ok": True}
