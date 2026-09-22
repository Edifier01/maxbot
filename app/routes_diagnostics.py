"""Secret-free, scoped diagnostics for authentication attempts."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from app.runtime import main as m


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
