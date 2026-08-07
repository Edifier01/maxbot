"""Panel API — settings."""

from __future__ import annotations

from fastapi import APIRouter

from app.routes_models import SettingsIn
from app.runtime import main as m
from app.tenant import is_admin

router = APIRouter(tags=["settings"])


@router.get("/api/settings")
async def get_settings():

    hide = {"api_pin", "telegram_bot_token"}
    out = {k: m.get_setting(k) for k in m.DEFAULTS if k not in hide}
    out["api_pin_set"] = m._pin_is_set()
    out["telegram_bot_token_set"] = bool(m.get_setting("telegram_bot_token").strip())
    out["vault"] = m.vault_status()
    with m._conn() as c:
        sched = c.execute("SELECT * FROM campaign_schedule WHERE id=1").fetchone()
    out["schedule"] = dict(sched) if sched else {"enabled": 0, "start_at": None}
    return out


@router.put("/api/settings")
async def update_settings(body: SettingsIn):

    data = body.model_dump(exclude_unset=True)
    if not is_admin():
        data.pop("worker_pool_size", None)
    if "api_pin" in data:
        pin = data.pop("api_pin")
        if pin is None or str(pin).strip() == "":
            m.set_setting("api_pin", "")
        else:
            m.set_setting("api_pin", m._hash_pin(str(pin).strip()))
    if "telegram_bot_token" in data:
        tok = data.pop("telegram_bot_token")
        if tok is None or str(tok).strip() == "":
            pass  # не затираем пустой строкой случайно — только явное
        else:
            m.set_setting("telegram_bot_token", str(tok).strip())
    prev_mode = m._message_pick_mode()
    for field, val in data.items():
        m.set_setting(field, "" if val is None else str(val))
    # legacy-поле = верхняя граница дневного лимита
    if "daily_limit_max" in data and "max_msgs_per_profile_day" not in data:
        m.set_setting("max_msgs_per_profile_day", str(data["daily_limit_max"]))
    if "message_pick_mode" in data and data["message_pick_mode"] != prev_mode:
        qs_mi = 0
        with m._conn() as c:
            row = c.execute("SELECT message_idx FROM queue_state WHERE id=1").fetchone()
            qs_mi = int(row["message_idx"] if row else 0)
        if qs_mi == 0:
            m._rebuild_message_bag()
    return {"ok": True}


@router.get("/api/settings/audit")
async def settings_audit(limit: int = 50):

    limit = min(max(limit, 1), 200)
    with m._conn() as c:
        rows = c.execute(
            "SELECT * FROM settings_audit ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


