"""Read-only scoped daily-plan view; it never materializes or samples."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.runtime import main as m


router = APIRouter(tags=["daily-plans"])


def _scope() -> str:
    if m._is_server_mode():
        from app.tenant import get_tenant_id

        tenant_id = get_tenant_id()
        return f"tenant:{tenant_id}" if tenant_id is not None else "global"
    return "local"


@router.get("/api/daily-plans/{profile_id}")
async def get_daily_plan(profile_id: int, business_date: str | None = None):
    day = business_date or m._local_today().isoformat()
    with m._conn() as connection:
        plan = connection.execute(
            "SELECT * FROM profile_daily_plans WHERE scope=? AND profile_id=? "
            "AND business_date=?",
            (_scope(), int(profile_id), day),
        ).fetchone()
        if plan is None:
            raise HTTPException(404, "daily plan is unavailable")
        slots = connection.execute(
            "SELECT slot_id, ordinal, item_id, pass_index, version_id, rendered_text, "
            "status, failure_reason, retry_count FROM profile_message_slots "
            "WHERE plan_id=? ORDER BY ordinal",
            (plan["plan_id"],),
        ).fetchall()
        return {
            "scope": _scope(),
            "plan": dict(plan),
            "slots": [dict(slot) for slot in slots],
        }
