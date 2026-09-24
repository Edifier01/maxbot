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
        start_utc, end_utc = m._local_day_utc_bounds()
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
                "WHERE sent_at>=? AND sent_at<? AND status='sent'",
                (start_utc, end_utc),
            ).fetchone()["n"]
            failed_today = c.execute(
                "SELECT COUNT(*) n FROM send_log "
                "WHERE sent_at>=? AND sent_at<? AND status='failed'",
                (start_utc, end_utc),
            ).fetchone()["n"]
            qs = c.execute("SELECT * FROM queue_state WHERE id=1").fetchone()
        items = []
        for p in profiles:
            d = redact_cabinet_row(m._profile_auth_view(p))
            if p["sent_day"] != today:
                d["messages_sent_today"] = 0
            d["circuit_open"] = m._is_circuit_open(p["id"])
            items.append(d)
        prog = m._daily_capacity_progress()
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


@router.get("/api/dashboard/attention")
async def dashboard_attention(offset: int = 0, limit: int = 10):
    """Return a paginated, read-only feed of profiles needing attention."""
    import time

    offset = max(0, int(offset))
    limit = min(50, max(1, int(limit)))
    try:
        with m._conn() as connection:
            rows = connection.execute(
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
                                SELECT 1 FROM group_profiles selected_gp
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
                LEFT JOIN group_profiles gp ON gp.profile_id=p.id AND gp.is_enabled=1
                LEFT JOIN groups g ON g.id=gp.group_id
                LEFT JOIN profile_automation_scope pas ON pas.profile_id=p.id
                GROUP BY p.id
                ORDER BY p.id
                """
            ).fetchall()

        runtimes = [runtime for _, runtime in m.REGISTRY.worker_items()]
        if not runtimes:
            runtimes = [m.RUNTIME]
        attention = []
        for row in rows:
            profile_id = int(row["id"])
            auth = m._auth_sessions.get(m._auth_session_key(profile_id), {})
            auth_step = str(auth.get("step", "idle"))
            cooldown_until = row["cooldown_until"]
            in_cooldown = m._is_in_cooldown(row)
            circuit_open = False
            for runtime in runtimes:
                errors = int(runtime.consecutive_errors.get(profile_id, 0) or 0)
                if errors < m.MAX_CONSECUTIVE_ERRORS:
                    continue
                opened_at = float(runtime.circuit_opened_at.get(profile_id, 0.0) or 0.0)
                minutes = max(
                    1.0,
                    m._setting_float("circuit_break_minutes", float(m.CIRCUIT_BREAK_MINUTES)),
                )
                if time.time() - opened_at <= minutes * 60:
                    circuit_open = True
                    break

            status = str(row["status"] or "")
            if status == "banned":
                priority = 0
            elif auth_step in {"waiting_sms", "waiting_cloud_password"}:
                priority = 1
            elif status == "needs_reauth":
                priority = 2
            elif status == "pending":
                priority = 3
            elif status == "disabled":
                priority = 4
            elif in_cooldown or circuit_open or auth_step == "error" or row["last_error"]:
                priority = 5
            else:
                continue

            from main import _sanitize_profile_error_view

            safe = _sanitize_profile_error_view(dict(row))
            current_attempt = m._current_auth_attempt(profile_id)
            item = redact_cabinet_row(
                {
                    "id": profile_id,
                    "phone": safe.get("phone", ""),
                    "label": safe.get("label", ""),
                    "status": status,
                    "last_error": safe.get("last_error", ""),
                    "last_error_code": safe.get("last_error_code", ""),
                    "last_error_action": safe.get("last_error_action", ""),
                    "auth_step": auth_step,
                    "attempt_id": current_attempt.attempt_id if current_attempt else None,
                    "in_cooldown": in_cooldown,
                    "cooldown_until": cooldown_until if in_cooldown else None,
                    "circuit_open": circuit_open,
                    "group_names": safe.get("group_names", ""),
                    "primary_group_id": safe.get("primary_group_id"),
                    "linked_group_count": int(safe.get("linked_group_count") or 0),
                }
            )
            attention.append((priority, profile_id, item))

        attention.sort(key=lambda entry: (entry[0], entry[1]))
        items = [entry[2] for entry in attention[offset : offset + limit]]
        return {"items": items, "total": len(attention), "offset": offset, "limit": limit}
    except HTTPException:
        raise
    except Exception as exc:
        info = classify_exception(
            exc, source="storage", stage="dashboard_attention", outcome="rejected"
        )
        import logging

        logging.getLogger(__name__).error(
            "dashboard attention failed code=%s source=%s stage=%s",
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
