"""Panel API — dashboard."""

from __future__ import annotations

import asyncio
from datetime import datetime
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from app.runtime import main as m
from app.services.errors import (
    classify_exception,
    classify_persisted_error,
    sanitize_log_line,
)
from app.tenant import redact_cabinet_row

router = APIRouter(tags=["dashboard"])


@router.post("/api/backup")
async def api_backup_now():

    path = await asyncio.to_thread(m.backup_database)
    if not path:
        raise HTTPException(500, "Не удалось создать резервную копию")
    return {"ok": True, "file": path.name}


@router.get("/api/backups")
async def api_list_backups():

    backups = m._backups_dir()
    backups.mkdir(parents=True, exist_ok=True)
    files = sorted(backups.glob("app-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {
        "items": [
            {
                "file": f.name,
                "size": f.stat().st_size,
                "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
            }
            for f in files[:50]
        ]
    }


@router.get("/api/log")
async def get_log():

    if m._is_server_mode():
        try:
            with m._conn() as c:
                rows = c.execute(
                    "SELECT msg FROM app_log ORDER BY id DESC LIMIT 200"
                ).fetchall()
            return {
                "lines": [
                    sanitize_log_line(r["msg"]) for r in reversed(rows)
                ]
            }
        except Exception as exc:
            import logging

            info = classify_exception(
                exc, source="storage", stage="log", outcome="rejected"
            )
            logging.getLogger(__name__).error(
                "tenant log read failed code=%s source=%s stage=%s",
                info.code,
                info.source,
                info.stage,
            )
            raise HTTPException(503, detail=asdict(info)) from None
    return {"lines": [sanitize_log_line(line) for line in m._log[-200:]]}


@router.get("/api/dashboard")
async def dashboard():

    """Сводка по всем профилям и группам для вкладки Dashboard."""
    import logging

    try:
        with m._conn() as c:
            counts = c.execute(
                "SELECT status, COUNT(*) n FROM profiles "
                "WHERE EXISTS (SELECT 1 FROM group_profiles gp WHERE gp.profile_id = profiles.id) "
                "GROUP BY status"
            ).fetchall()
            profiles = c.execute(
                """
                SELECT p.*,
                       GROUP_CONCAT(g.name, ', ') AS group_names,
                       COUNT(DISTINCT gp.group_id) AS linked_group_count,
                       pas.automation_group_id,
                       pas.consent_state AS automation_scope_state,
                       CASE
                         WHEN pas.profile_id IS NOT NULL THEN
                           CASE
                             WHEN pas.consent_state='active'
                              AND pas.automation_group_id IS NOT NULL
                              AND EXISTS (
                                SELECT 1
                                FROM group_profiles selected_gp
                                WHERE selected_gp.profile_id=p.id
                                  AND selected_gp.group_id=pas.automation_group_id
                                  AND selected_gp.is_enabled=1
                              )
                             THEN pas.automation_group_id
                             ELSE NULL
                           END
                         WHEN COUNT(DISTINCT gp.group_id)=1 THEN MIN(g.id)
                         ELSE NULL
                       END AS primary_group_id
                FROM profiles p
                JOIN group_profiles gp ON gp.profile_id = p.id AND gp.is_enabled=1
                JOIN groups g ON g.id = gp.group_id
                LEFT JOIN profile_automation_scope pas ON pas.profile_id = p.id
                GROUP BY p.id
                ORDER BY
                  CASE p.status
                    WHEN 'needs_reauth' THEN 0
                    WHEN 'pending' THEN 1
                    WHEN 'active' THEN 2
                    ELSE 3
                  END,
                  p.id
                LIMIT 500
                """
            ).fetchall()
            groups_n = c.execute("SELECT COUNT(*) n FROM groups").fetchone()["n"]
            today = m._local_today().isoformat()
            sent_today = c.execute(
                "SELECT COUNT(*) n FROM send_log "
                "WHERE date(sent_at, '+3 hours')=? AND status='sent'",
                (today,),
            ).fetchone()["n"]
            failed_today = c.execute(
                "SELECT COUNT(*) n FROM send_log "
                "WHERE date(sent_at, '+3 hours')=? AND status='failed'",
                (today,),
            ).fetchone()["n"]
            qs = c.execute("SELECT * FROM queue_state WHERE id=1").fetchone()
        items = []
        for p in profiles:
            d = redact_cabinet_row(m._profile_auth_view(p))
            if p["sent_day"] != today:
                d["messages_sent_today"] = 0
            d["circuit_open"] = m._is_circuit_open(p["id"])
            items.append(d)
        if m._campaign_goal() == "daily_limits":
            prog = m._daily_capacity_progress()
        else:
            msgs = len(m.load_message_pool())
            mi = int(qs["message_idx"] if qs else 0)
            prog = {
                "goal": "message_pool",
                "sent": min(mi, msgs),
                "total": msgs,
                "remaining": max(0, msgs - mi),
            }
        return {
            "counts": {r["status"]: r["n"] for r in counts},
            "groups_count": groups_n,
            "sent_today": sent_today,
            "failed_today": failed_today,
            "circuit_open": m._circuit_open_count(),
            "running": bool(qs and qs["running"]),
            "auto_run": m._auto_run_enabled(),
            "campaign_progress": prog,
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as exc:
        info = classify_exception(
            exc, source="storage", stage="dashboard", outcome="rejected"
        )
        logging.getLogger(__name__).error(
            "dashboard failed code=%s source=%s stage=%s",
            info.code,
            info.source,
            info.stage,
        )
        raise HTTPException(500, detail=asdict(info)) from None


@router.get("/api/send_log")
async def get_send_log(
    offset: int = 0,
    limit: int = 50,
    q: str = "",
    status: str = "",
):

    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    where = ["1=1"]
    params: list[Any] = []
    if status.strip():
        where.append("sl.status = ?")
        params.append(status.strip())
    if q.strip():
        where.append(
            "(p.phone LIKE ? OR p.label LIKE ? OR g.name LIKE ? OR sl.error LIKE ? "
            "OR CAST(sl.profile_id AS TEXT) LIKE ?)"
        )
        like = f"%{q.strip()}%"
        params.extend([like, like, like, like, like])
    where_sql = " AND ".join(where)
    with m._conn() as c:
        total = c.execute(
            f"""
            SELECT COUNT(*) n
            FROM send_log sl
            LEFT JOIN profiles p ON p.id = sl.profile_id
            LEFT JOIN groups g ON g.id = sl.group_id
            WHERE {where_sql}
            """,
            params,
        ).fetchone()["n"]
        rows = c.execute(
            f"""
            SELECT sl.*, datetime(sl.sent_at, '+3 hours') AS sent_at_utc3,
                   p.phone, p.label, g.name AS group_name
            FROM send_log sl
            LEFT JOIN profiles p ON p.id = sl.profile_id
            LEFT JOIN groups g ON g.id = sl.group_id
            WHERE {where_sql}
            ORDER BY sl.id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["sent_at"] = item.pop("sent_at_utc3")
        raw_error = str(item.get("error") or "")
        if raw_error:
            info = classify_persisted_error(
                raw_error, source="max", stage="send", outcome="rejected"
            )
            item["error"] = info.safe_message
            item["error_code"] = info.code
            item["error_source"] = info.source
            item["error_stage"] = info.stage
            item["error_action"] = info.recommended_action
        items.append(redact_cabinet_row(item))
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "q": q,
        "status": status,
    }
