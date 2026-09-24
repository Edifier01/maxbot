"""Secret-free, scoped diagnostics for authentication attempts."""

from __future__ import annotations

import re
import json

from fastapi import APIRouter, HTTPException
from starlette.responses import Response

from app.runtime import main as m
from app.tenant import is_cabinet_user


router = APIRouter(tags=["diagnostics"])
_ATTEMPT_RE = re.compile(r"profile-(?P<profile_id>[1-9][0-9]*)\Z")


def _mask_phone(phone: str) -> str:
    value = str(phone or "")
    if len(value) <= 4:
        return "••••"
    return f"{value[:5]}••••••{value[-2:]}"


def _safe_next_action(step: str) -> str:
    return {
        "waiting_sms": "submit_code",
        "verifying_sms": "wait_verification",
        "waiting_cloud_password": "submit_password",
        "verifying_password": "wait_verification",
        "connecting": "wait_connection",
        "error": "review_error",
    }.get(step, "start_or_continue")


@router.get("/api/profiles/{profile_id}/auth-attempts/{attempt_id}/diagnostic")
async def export_current_auth_attempt(
    profile_id: int, attempt_id: str, download: bool = False
):
    """Preview or download a strict safe projection of the current attempt."""
    if m._is_server_mode() and not is_cabinet_user():
        raise HTTPException(403, "Недоступно в личном кабинете")

    attempt = m._current_auth_attempt(profile_id)
    if attempt is None or str(attempt.attempt_id) != str(attempt_id):
        raise HTTPException(404, "Попытка не найдена")

    with m._conn() as connection:
        row = connection.execute(
            "SELECT phone, status, last_error FROM profiles WHERE id=?",
            (int(profile_id),),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Попытка не найдена")

    payload = {
        "attempt_id": str(attempt.attempt_id),
        "phone": _mask_phone(str(row["phone"] or "")),
        "status": str(row["status"] or "unknown"),
        "auth_step": str(attempt.auth_step),
        "next_action": _safe_next_action(str(attempt.auth_step)),
        "has_error": bool(
            str(row["last_error"] or "").strip() or attempt.error_code
        ),
        "retention": "metadata_only",
    }
    if not download:
        return payload
    return Response(
        content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="auth-attempt.json"'},
    )


@router.get("/api/diagnostics/auth-attempts/{attempt_id}")
async def get_auth_attempt_diagnostic(attempt_id: str):
    match = _ATTEMPT_RE.fullmatch(str(attempt_id))
    if match is None:
        raise HTTPException(404, "Попытка не найдена")
    profile_id = int(match.group("profile_id"))
    with m._conn() as connection:
        row = connection.execute(
            "SELECT id, phone, status, last_error FROM profiles WHERE id=?",
            (profile_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Попытка не найдена")

    session = m._auth_sessions.get(m._auth_session_key(profile_id), {})
    step = str(session.get("step", "idle"))
    return {
        "attempt_id": f"profile-{profile_id}",
        "profile_id": profile_id,
        "phone": _mask_phone(str(row["phone"] or "")),
        "status": str(row["status"] or "unknown"),
        "auth_step": step,
        "next_action": _safe_next_action(step),
        "has_error": bool(str(row["last_error"] or "").strip()),
        "retention": "runtime_only",
    }
