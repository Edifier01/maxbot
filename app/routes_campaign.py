"""Campaign start/stop/pause/schedule API."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Iterator, Mapping

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from app import recovery_hold
from app.runtime import main as m

router = APIRouter(tags=["campaign"])


@dataclass(frozen=True)
class ReadinessReport:
    version: str
    scope: str
    checks: dict[str, bool]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    selection: dict[str, object]

    @property
    def ready(self) -> bool:
        return not self.blockers and all(self.checks.values())


@dataclass(frozen=True)
class CommandResult:
    id: str
    accepted: bool
    state: str
    generation: int
    payload: dict[str, object] | None = None


def build_readiness(
    *,
    version: str,
    scope: str,
    checks: Mapping[str, bool],
    blockers: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    selection: Mapping[str, object] | None = None,
) -> ReadinessReport:
    if not str(scope).strip():
        raise ValueError("scope is required")
    normalized = {str(key): bool(value) for key, value in checks.items()}
    derived = list(blockers)
    for key, value in normalized.items():
        if not value and key not in derived:
            derived.append(key)
    return ReadinessReport(
        version=str(version),
        scope=str(scope),
        checks=normalized,
        blockers=tuple(derived),
        warnings=tuple(warnings),
        selection=dict(selection or {}),
    )


class CampaignCommandCoordinator:
    """Persist Start/Stop intent and fence stale preflight generations."""

    def __init__(self, connection: sqlite3.Connection, *, scope: str) -> None:
        self.connection = connection
        self.scope = str(scope)
        if not self.scope.strip():
            raise ValueError("scope is required")
        if self.connection.row_factory is None:
            self.connection.row_factory = sqlite3.Row
        self._ensure_schema()
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO campaign_control "
                "(scope, generation, auto_run, stop_requested, state, updated_at) "
                "VALUES (?, 0, 0, 0, 'stopped', datetime('now'))",
                (self.scope,),
            )

    def _ensure_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS campaign_control (
                scope TEXT PRIMARY KEY,
                generation INTEGER NOT NULL,
                auto_run INTEGER NOT NULL DEFAULT 0,
                stop_requested INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS campaign_command_receipts (
                scope TEXT NOT NULL,
                request_id TEXT NOT NULL,
                command TEXT NOT NULL,
                result_id TEXT NOT NULL,
                accepted INTEGER NOT NULL,
                state TEXT NOT NULL,
                generation INTEGER NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                PRIMARY KEY (scope, request_id, command)
            );
            """
        )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def preview(self, report: ReadinessReport) -> ReadinessReport:
        if report.scope != self.scope:
            raise ValueError("readiness scope mismatch")
        return report

    def begin_start(self, request_id: str, report: ReadinessReport) -> CommandResult:
        if report.scope != self.scope:
            raise ValueError("readiness scope mismatch")
        with self._transaction() as connection:
            previous = self._receipt(request_id, "start")
            if previous is not None:
                return previous
            control = self._control()
            if not report.ready:
                result = CommandResult(
                    id=f"start-{uuid.uuid4().hex}",
                    accepted=False,
                    state="blocked",
                    generation=int(control["generation"]),
                    payload={"blockers": list(report.blockers)},
                )
                self._insert_receipt(request_id, "start", result)
                return result
            generation = int(control["generation"]) + 1
            connection.execute(
                "UPDATE campaign_control SET generation=?, auto_run=0, "
                "stop_requested=0, state='preflight', updated_at=datetime('now') "
                "WHERE scope=?",
                (generation, self.scope),
            )
            result = CommandResult(
                id=f"start-{uuid.uuid4().hex}",
                accepted=True,
                state="preflight",
                generation=generation,
                payload={"version": report.version},
            )
            self._insert_receipt(request_id, "start", result)
            return result

    def complete_start(self, request_id: str) -> CommandResult:
        with self._transaction() as connection:
            result = self._receipt(request_id, "start")
            if result is None:
                raise ValueError("start request not found")
            if result.state != "preflight":
                return result
            control = self._control()
            if (
                int(control["generation"]) != result.generation
                or int(control["stop_requested"]) != 0
            ):
                fenced = CommandResult(
                    id=result.id,
                    accepted=False,
                    state="fenced_by_stop",
                    generation=int(control["generation"]),
                    payload=result.payload,
                )
                self._replace_receipt(request_id, "start", fenced)
                return fenced
            connection.execute(
                "UPDATE campaign_control SET auto_run=1, state='running', "
                "updated_at=datetime('now') WHERE scope=?",
                (self.scope,),
            )
            running = CommandResult(
                id=result.id,
                accepted=True,
                state="running",
                generation=result.generation,
                payload=result.payload,
            )
            self._replace_receipt(request_id, "start", running)
            return running

    def fail_start(self, request_id: str) -> CommandResult:
        """Close a failed preflight without releasing a newer Stop fence."""
        with self._transaction() as connection:
            result = self._receipt(request_id, "start")
            if result is None:
                raise ValueError("start request not found")
            if result.state != "preflight":
                return result
            control = self._control()
            if int(control["generation"]) == result.generation:
                generation = result.generation + 1
                connection.execute(
                    "UPDATE campaign_control SET generation=?, auto_run=0, "
                    "stop_requested=1, state='stopped', updated_at=datetime('now') "
                    "WHERE scope=?",
                    (generation, self.scope),
                )
                failed = CommandResult(
                    id=result.id,
                    accepted=False,
                    state="failed",
                    generation=generation,
                    payload=result.payload,
                )
            else:
                failed = CommandResult(
                    id=result.id,
                    accepted=False,
                    state="fenced_by_stop",
                    generation=int(control["generation"]),
                    payload=result.payload,
                )
            self._replace_receipt(request_id, "start", failed)
            return failed

    def stop(self, request_id: str) -> CommandResult:
        with self._transaction() as connection:
            previous = self._receipt(request_id, "stop")
            if previous is not None:
                return previous
            control = self._control()
            generation = int(control["generation"]) + 1
            connection.execute(
                "UPDATE campaign_control SET generation=?, auto_run=0, "
                "stop_requested=1, state='stopping', updated_at=datetime('now') "
                "WHERE scope=?",
                (generation, self.scope),
            )
            result = CommandResult(
                id=f"stop-{uuid.uuid4().hex}",
                accepted=True,
                state="stopping",
                generation=generation,
                payload={},
            )
            self._insert_receipt(request_id, "stop", result)
            return result

    def complete_stop(self, request_id: str, *, state: str = "stopped") -> CommandResult:
        with self._transaction() as connection:
            result = self._receipt(request_id, "stop")
            if result is None:
                raise ValueError("stop request not found")
            if result.state != "stopping":
                return result
            control = self._control()
            if int(control["generation"]) != result.generation:
                return result
            safe_state = state if state in {"stopped", "paused"} else "stopped"
            connection.execute(
                "UPDATE campaign_control SET auto_run=0, stop_requested=1, "
                "state=?, updated_at=datetime('now') WHERE scope=?",
                (safe_state, self.scope),
            )
            completed = CommandResult(
                id=result.id,
                accepted=True,
                state=safe_state,
                generation=result.generation,
                payload=result.payload,
            )
            self._replace_receipt(request_id, "stop", completed)
            return completed

    def can_claim(self, generation: int) -> bool:
        control = self._control()
        return (
            int(control["generation"]) == int(generation)
            and int(control["auto_run"]) == 1
            and int(control["stop_requested"]) == 0
        )

    def can_complete_start(self, generation: int) -> bool:
        """Check the preflight fence without requiring running state yet."""
        control = self._control()
        return (
            int(control["generation"]) == int(generation)
            and int(control["stop_requested"]) == 0
        )

    def _control(self):
        row = self.connection.execute(
            "SELECT * FROM campaign_control WHERE scope=?", (self.scope,)
        ).fetchone()
        if row is None:
            raise RuntimeError("campaign control is missing")
        return row

    def _receipt(self, request_id: str, command: str) -> CommandResult | None:
        row = self.connection.execute(
            "SELECT * FROM campaign_command_receipts WHERE scope=? AND request_id=? "
            "AND command=?",
            (self.scope, request_id, command),
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        return CommandResult(
            id=str(row["result_id"]),
            accepted=bool(row["accepted"]),
            state=str(row["state"]),
            generation=int(row["generation"]),
            payload=payload if isinstance(payload, dict) else {},
        )

    def _insert_receipt(self, request_id: str, command: str, result: CommandResult) -> None:
        self.connection.execute(
            "INSERT INTO campaign_command_receipts "
            "(scope, request_id, command, result_id, accepted, state, generation, "
            "payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (
                self.scope,
                request_id,
                command,
                result.id,
                int(result.accepted),
                result.state,
                result.generation,
                json.dumps(result.payload or {}, sort_keys=True),
            ),
        )

    def _replace_receipt(self, request_id: str, command: str, result: CommandResult) -> None:
        self.connection.execute(
            "UPDATE campaign_command_receipts SET result_id=?, accepted=?, state=?, "
            "generation=?, payload_json=? WHERE scope=? AND request_id=? AND command=?",
            (
                result.id,
                int(result.accepted),
                result.state,
                result.generation,
                json.dumps(result.payload or {}, sort_keys=True),
                self.scope,
                request_id,
                command,
            ),
        )


class ScheduleIn(BaseModel):
    start_at: str  # ISO-8601


def _campaign_scope() -> str:
    if not m._is_server_mode():
        return "local"
    from app.tenant import get_tenant_id

    tenant_id = get_tenant_id()
    return f"tenant:{int(tenant_id)}" if tenant_id is not None else "global"


def _coordinator() -> CampaignCommandCoordinator:
    return CampaignCommandCoordinator(m._conn(), scope=_campaign_scope())


def _request_id(value: str | None) -> str:
    return str(value or "").strip() or f"http-{uuid.uuid4().hex}"


def _library_available(messages: list[str]) -> bool:
    if messages:
        return True
    try:
        connection, scope = m._message_library_storage()
        row = connection.execute(
            "SELECT 1 FROM message_set_versions WHERE scope=? AND is_current=1 LIMIT 1",
            (scope,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


@router.post("/api/campaign/start")
async def campaign_start(
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
):

    recovery_hold.require_external_actions_released()
    m._require_vault_unlocked()
    messages = m.load_message_pool()
    if not _library_available(messages):
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
    command_id = _request_id(request_id)
    coordinator = _coordinator()
    report = build_readiness(
        version=str(getattr(m, "APP_VERSION", "unknown")),
        scope=coordinator.scope,
        checks={"library": True, "groups": True, "profiles": True},
        selection={"messages": len(messages)},
    )
    pending = coordinator.begin_start(command_id, report)
    if not pending.accepted:
        raise HTTPException(409, {"state": pending.state, "blockers": pending.payload})
    if pending.state == "running":
        return {
            "ok": True,
            "state": pending.state,
            "generation": pending.generation,
            "campaign_id": m.RUNTIME.current_campaign_id,
        }
    try:
        await m._preflight_group_proxies()
    except Exception:
        coordinator.fail_start(command_id)
        raise
    if not coordinator.can_complete_start(pending.generation):
        fenced = coordinator.fail_start(command_id)
        raise HTTPException(409, {"state": fenced.state})
    running = coordinator.complete_start(command_id)
    if not running.accepted:
        raise HTTPException(409, {"state": running.state})
    m.set_setting("auto_run", "1")
    started = await m._start_worker(control_generation=running.generation)
    if not started:
        coordinator.fail_start(command_id)
        m.set_setting("auto_run", "0")
        raise HTTPException(409, "Воркер занят или команда устарела")
    return {
        "ok": True,
        "state": running.state,
        "generation": running.generation,
        "campaign_id": m.RUNTIME.current_campaign_id,
    }


@router.post("/api/campaign/stop")
async def campaign_stop(
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
):

    command_id = _request_id(request_id)
    coordinator = _coordinator()
    intent = coordinator.stop(command_id)
    if intent.state == "stopped":
        return {"ok": True, "state": intent.state, "generation": intent.generation}
    m.set_setting("auto_run", "0")
    await m._stop_worker(finish_status="stopped", reason="Остановлено пользователем")
    completed = coordinator.complete_stop(command_id)
    return {"ok": True, "state": completed.state, "generation": completed.generation}


@router.post("/api/campaign/pause")
async def campaign_pause(
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
):

    command_id = _request_id(request_id)
    coordinator = _coordinator()
    intent = coordinator.stop(command_id)
    if intent.state == "stopped":
        return {"ok": True, "state": intent.state, "generation": intent.generation}
    m.set_setting("auto_run", "0")
    await m._stop_worker(finish_status="paused", reason="Пауза")
    completed = coordinator.complete_stop(command_id, state="paused")
    m.append_log("Рассылка на паузе")
    return {"ok": True, "state": completed.state, "generation": completed.generation}


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
    raise HTTPException(409, "Безопасный повтор временно недоступен")


@router.post("/api/campaign/test")
async def campaign_test():

    recovery_hold.require_external_actions_released()
    m._require_vault_unlocked()
    if m.RUNTIME.worker_busy():
        raise HTTPException(409, "кампания идёт")
    messages = m.load_message_pool()
    if not _library_available(messages):
        raise HTTPException(400, "Нет сообщений")
    groups = m._active_groups()
    if not groups:
        raise HTTPException(400, "Нет групп")
    daily_job = None
    if _library_available(messages):
        from app.campaign_worker import _claim_daily_job_sync

        daily_candidate = _claim_daily_job_sync()
        if isinstance(daily_candidate, dict):
            daily_job = daily_candidate
        elif daily_candidate in {"DAILY_WAIT", "DAILY_DONE"}:
            raise HTTPException(409, "Нет доступного дневного slot")
    profile = None
    group = None
    if daily_job is not None:
        profile = daily_job["profile"]
        group = daily_job["group"]
    else:
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
    text = daily_job["text"] if daily_job is not None else messages[0]
    from app.campaign_send import SendTracker

    tracker = SendTracker()
    try:
        await m._preflight_group_proxies()
        ok = await m._send_with_retry(
            profile,
            group,
            text,
            0,
            0,
            0,
            0,
            advance_queue=False,
            daily_plan_id=(daily_job or {}).get("daily_plan_id"),
            slot_id=(daily_job or {}).get("slot_id"),
            tracker=tracker,
        )
    except BaseException:
        if daily_job is not None:
            from app.campaign_worker import _finalize_daily_job

            _finalize_daily_job(daily_job, False, tracker)
        raise
    if daily_job is not None:
        from app.campaign_worker import _finalize_daily_job

        _finalize_daily_job(daily_job, ok, tracker)
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
