"""Campaign start/stop/pause/schedule API."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.runtime import main as m

router = APIRouter(tags=["campaign"])


class ScheduleIn(BaseModel):
    start_at: str  # ISO-8601


@router.post("/api/campaign/start")
async def campaign_start():

    m._require_vault_unlocked()
    messages = m.load_message_pool()
    if not messages:
        raise HTTPException(
            400, "Нет файла сообщений. Обратитесь к администратору."
        )
    if not m._active_groups():
        raise HTTPException(400, "Создайте хотя бы одну группу")
    if not m._has_active_profiles():
        raise HTTPException(400, "Нет активных профилей — войдите в аккаунты")
    if not m._has_sendable_profile():
        raise HTTPException(
            400,
            "Некому отправлять: все профили исчерпали дневной лимит или не авторизованы",
        )
    await m._preflight_group_proxies()
    m.set_setting("auto_run", "1")
    await m._start_worker()
    return {"ok": True, "campaign_id": m.RUNTIME.current_campaign_id}


@router.post("/api/campaign/stop")
async def campaign_stop():

    m.set_setting("auto_run", "0")
    await m._stop_worker(finish_status="stopped", reason="Остановлено пользователем")
    return {"ok": True}


@router.post("/api/campaign/pause")
async def campaign_pause():

    m.set_setting("auto_run", "0")
    await m._stop_worker(finish_status="paused", reason="Пауза")
    m.append_log("Рассылка на паузе")
    return {"ok": True}


@router.post("/api/campaign/reset")
async def campaign_reset():

    if m.RUNTIME.worker_busy():
        raise HTTPException(400, "Остановите рассылку перед сбросом прогресса")
    m._reset_queue_progress()
    m.append_log("Прогресс рассылки сброшен")
    return {"ok": True}


@router.post("/api/campaign/schedule")
async def campaign_schedule(body: ScheduleIn):

    try:
        start_at = m._parse_iso_datetime(body.start_at)
    except ValueError as e:
        raise HTTPException(400, f"Некорректная дата: {e}") from e
    if start_at <= datetime.now(timezone.utc):
        raise HTTPException(400, "Время старта должно быть в будущем")
    iso = start_at.isoformat()
    with m._conn() as c:
        c.execute(
            "UPDATE campaign_schedule SET start_at=?, enabled=1, "
            "created_at=datetime('now') WHERE id=1",
            (iso,),
        )
    m.append_log(f"Рассылка запланирована на {iso}")
    return {"ok": True, "start_at": iso, "enabled": True}


@router.delete("/api/campaign/schedule")
async def campaign_schedule_cancel():

    with m._conn() as c:
        c.execute("UPDATE campaign_schedule SET enabled=0, start_at=NULL WHERE id=1")
    m.append_log("Расписание отменено")
    return {"ok": True}


@router.get("/api/campaign/schedule")
async def campaign_schedule_get():

    with m._conn() as c:
        row = c.execute("SELECT * FROM campaign_schedule WHERE id=1").fetchone()
    return dict(row) if row else {"enabled": 0, "start_at": None}


@router.post("/api/campaign/retry_failed")
async def campaign_retry_failed():

    m._require_vault_unlocked()
    if m.RUNTIME.worker_busy():
        raise HTTPException(400, "Сначала остановите текущую рассылку")
    with m._conn() as c:
        row = c.execute(
            """
            SELECT MIN(sl.message_idx) AS mi
            FROM send_log sl
            WHERE sl.status='failed'
              AND NOT EXISTS (
                SELECT 1 FROM send_log s2
                WHERE s2.message_idx = sl.message_idx AND s2.status='sent'
              )
            """
        ).fetchone()
    if row is None or row["mi"] is None:
        raise HTTPException(400, "Нет ошибочных сообщений для повтора")
    mi = int(row["mi"])
    with m._conn() as c:
        c.execute(
            "UPDATE queue_state SET message_idx=?, profile_idx=0, group_idx=0 WHERE id=1",
            (mi,),
        )
    m.append_log(f"Повтор ошибок: продолжение с индекса={mi}")
    if not m._has_sendable_profile():
        raise HTTPException(400, "Нет доступных профилей для отправки")
    await m._preflight_group_proxies()
    m.set_setting("auto_run", "1")
    await m._start_worker()
    return {"ok": True, "message_idx": mi, "campaign_id": m.RUNTIME.current_campaign_id}


@router.post("/api/campaign/test")
async def campaign_test():

    m._require_vault_unlocked()
    if m.RUNTIME.worker_busy():
        raise HTTPException(409, "кампания идёт")
    messages = m.load_message_pool()
    if not messages:
        raise HTTPException(400, "Нет сообщений")
    groups = m._active_groups()
    if not groups:
        raise HTTPException(400, "Нет групп")
    profile = None
    group = None
    for g in groups:
        profiles = m._active_profiles_for_group(g["id"])
        for p in profiles:
            if m._is_circuit_open(p["id"]):
                continue
            if m._can_send_in_group(p, g["id"]):
                profile, group = p, g
                break
        if profile:
            break
    if not profile or not group:
        raise HTTPException(400, "Нет активного профиля для теста")
    text = messages[0]
    await m._preflight_group_proxies()
    ok = await m._send_with_retry(
        profile, group, text, 0, 0, 0, 0, advance_queue=False
    )
    if not ok:
        raise HTTPException(502, "Тест не удался — смотрите лог / нужен повторный вход")
    m.append_log(f"Тест отправки успешен #{profile['id']} → «{group['name']}»")
    return {
        "ok": True,
        "profile_id": profile["id"],
        "phone": profile["phone"],
        "group_id": group["id"],
        "text_preview": text[:80],
    }


@router.get("/api/campaigns")
async def list_campaigns(limit: int = 50):

    limit = min(max(limit, 1), 200)
    with m._conn() as c:
        rows = c.execute(
            "SELECT * FROM campaigns ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"items": [dict(r) for r in rows]}
