"""Campaign start/stop/pause/schedule API."""

from __future__ import annotations

import asyncio
import json
import hashlib
import hmac
from math import ceil
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from collections.abc import Iterator, Mapping
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from app.campaign_runtime import REGISTRY
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
    replayed: bool = field(default=False, compare=False)


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
            if str(control["state"]) == "testing":
                result = CommandResult(
                    id=f"start-{uuid.uuid4().hex}",
                    accepted=False,
                    state="test_in_progress",
                    generation=int(control["generation"]),
                    payload={"reason": "campaign_test_in_progress"},
                )
                self._insert_receipt(request_id, "start", result)
                return result
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
        """Close a failed start without releasing a newer Stop fence."""
        with self._transaction() as connection:
            result = self._receipt(request_id, "start")
            if result is None:
                raise ValueError("start request not found")
            if result.state not in {"preflight", "running"}:
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

    def begin_test(self, request_id: str) -> CommandResult:
        """Reserve the stopped campaign generation for one manual test."""
        with self._transaction() as connection:
            previous = self._receipt(request_id, "test")
            if previous is not None:
                return previous
            control = self._control()
            state = str(control["state"])
            if (
                state not in {"stopped", "paused"}
                or int(control["auto_run"]) != 0
            ):
                result = CommandResult(
                    id=f"test-{uuid.uuid4().hex}",
                    accepted=False,
                    state="campaign_busy",
                    generation=int(control["generation"]),
                    payload={"reason": "campaign_control_busy"},
                )
                self._insert_receipt(request_id, "test", result)
                return result
            generation = int(control["generation"])
            connection.execute(
                "UPDATE campaign_control SET state='testing', auto_run=0, "
                "stop_requested=0, updated_at=datetime('now') WHERE scope=?",
                (self.scope,),
            )
            result = CommandResult(
                id=f"test-{uuid.uuid4().hex}",
                accepted=True,
                state="testing",
                generation=generation,
                payload={},
            )
            self._insert_receipt(request_id, "test", result)
            return result

    def complete_test(self, request_id: str) -> CommandResult:
        with self._transaction() as connection:
            result = self._receipt(request_id, "test")
            if result is None:
                raise ValueError("test request not found")
            if result.state != "testing":
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
                self._replace_receipt(request_id, "test", fenced)
                return fenced
            connection.execute(
                "UPDATE campaign_control SET state='stopped', auto_run=0, "
                "stop_requested=0, updated_at=datetime('now') WHERE scope=?",
                (self.scope,),
            )
            completed = CommandResult(
                id=result.id,
                accepted=True,
                state="stopped",
                generation=result.generation,
                payload=result.payload,
            )
            self._replace_receipt(request_id, "test", completed)
            return completed

    def fail_test(self, request_id: str) -> CommandResult:
        """Close a failed test without overwriting a newer Stop fence."""
        with self._transaction() as connection:
            result = self._receipt(request_id, "test")
            if result is None:
                raise ValueError("test request not found")
            if result.state != "testing":
                return result
            control = self._control()
            if int(control["generation"]) == result.generation:
                connection.execute(
                    "UPDATE campaign_control SET state='stopped', auto_run=0, "
                    "stop_requested=0, updated_at=datetime('now') WHERE scope=?",
                    (self.scope,),
                )
                failed = CommandResult(
                    id=result.id,
                    accepted=False,
                    state="failed",
                    generation=result.generation,
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
            self._replace_receipt(request_id, "test", failed)
            return failed

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
            replayed=True,
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


class CampaignStartIn(BaseModel):
    readiness_revision: str | None = Field(default=None, min_length=1, max_length=128)


def _campaign_scope() -> str:
    if not m._is_server_mode():
        return "local"
    from app.tenant import get_tenant_id

    tenant_id = get_tenant_id()
    return f"tenant:{int(tenant_id)}" if tenant_id is not None else "global"


def _coordinator() -> CampaignCommandCoordinator:
    return CampaignCommandCoordinator(m._conn(), scope=_campaign_scope())


@router.get("/api/campaign/command-status")
async def campaign_command_status(
    command: Literal["start", "stop", "pause", "test"],
    request_id: str = Query(min_length=1, max_length=128),
):
    """Read a persisted command receipt in the caller's current tenant scope."""
    receipt_command = "stop" if command == "pause" else command
    connection = m._conn()
    if m.DB_BACKEND == "postgres":
        table = connection.execute(
            "SELECT to_regclass('campaign_command_receipts')"
        ).fetchone()
        if table is None or table[0] is None:
            return {"known": False, "state": "not_found"}
    else:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            ("campaign_command_receipts",),
        ).fetchone()
        if table is None:
            return {"known": False, "state": "not_found"}
    row = connection.execute(
        "SELECT state, accepted, generation FROM campaign_command_receipts "
        "WHERE scope=? AND request_id=? AND command=?",
        (_campaign_scope(), request_id, receipt_command),
    ).fetchone()
    if row is None:
        return {"known": False, "state": "not_found"}
    state = str(row[0])
    if command == "test" and state in {"failed", "fenced_by_stop"}:
        # A lost response cannot distinguish a proven-unsent test from an
        # ambiguous external outcome. Keep it unresolved so the UI won't
        # release the request ID and allow another test send.
        state = "unknown"
    return {
        "known": True,
        "command": command,
        "state": state,
        "accepted": bool(row[1]),
        "generation": int(row[2]),
    }


def _persist_stop_intent(request_id: str) -> CommandResult:
    """Run the synchronous campaign-control transaction off the event loop."""
    return _coordinator().stop(request_id)


def _persist_stop_completion(request_id: str, state: str) -> CommandResult:
    """Complete a Stop/Pause transaction on the worker thread as well."""
    return _coordinator().complete_stop(request_id, state=state)


def _request_id(value: str | None) -> str:
    return str(value or "").strip() or f"http-{uuid.uuid4().hex}"


def _library_available(messages: list[str]) -> bool:
    if messages:
        return True
    try:
        connection, scope = m._message_library_source_storage()
        row = connection.execute(
            "SELECT 1 FROM message_set_versions WHERE scope=? AND is_current=1 LIMIT 1",
            (scope,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


_READINESS_POLICY_KEYS = (
    "campaign_goal",
    "daily_limit_min",
    "daily_limit_max",
    "max_msgs_per_profile_day",
    "message_pick_mode",
    "role_plan_enabled",
    "role_quiet_limit",
    "delay_min_sec",
    "delay_max_sec",
    "human_rhythm_enabled",
    "human_pauses_enabled",
    "short_pause_chance",
    "short_pause_min_sec",
    "short_pause_max_sec",
    "long_pause_chance",
    "long_pause_min_sec",
    "long_pause_max_sec",
    "send_windows_weekday",
    "send_windows_weekend",
)


def _table_rows(
    connection: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
) -> list[dict[str, object]]:
    """Read a stable, non-secret table projection without creating schema."""
    try:
        available = {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        selected = [column for column in columns if column in available]
        if not selected:
            return []
        order = f" ORDER BY {', '.join(selected)}"
        rows = connection.execute(
            f"SELECT {', '.join(selected)} FROM {table}{order}"
        ).fetchall()
    except sqlite3.Error:
        return []
    return [{column: row[column] for column in selected} for row in rows]


def _readiness_snapshot() -> dict[str, object]:
    """Build the preview fingerprint from read-only local state only."""
    library: dict[str, object] = {"scope": "", "version_id": None, "checksum": None}
    business_date = m._local_today().isoformat()
    try:
        library_connection, library_scope = m._message_library_source_storage()
        library["scope"] = library_scope
        row = library_connection.execute(
            "SELECT version_id, checksum, item_count FROM message_set_versions "
            "WHERE scope=? AND is_current=1 ORDER BY created_at DESC LIMIT 1",
            (library_scope,),
        ).fetchone()
        if row is not None:
            library.update(
                {
                    "version_id": str(row["version_id"]),
                    "checksum": str(row["checksum"]),
                    "item_count": int(row["item_count"]),
                }
            )
    except sqlite3.Error:
        library["unavailable"] = True

    with m._conn() as connection:
        tables = {
            "profiles": _table_rows(
                connection,
                "profiles",
                (
                    "id",
                    "status",
                    "messages_sent_today",
                    "sent_day",
                    "daily_limit",
                    "daily_limit_day",
                    "cooldown_until",
                ),
            ),
            "groups": _table_rows(
                connection,
                "groups",
                ("id", "is_active", "destination_revision", "destination_verified"),
            ),
            "group_profiles": _table_rows(
                connection,
                "group_profiles",
                ("group_id", "profile_id", "is_enabled", "role_day", "day_role", "day_order"),
            ),
            "routes": _table_rows(
                connection,
                "profile_route_assignments",
                ("profile_id", "automation_group_id", "connection_id", "route_version"),
            ),
            "automation_scope": _table_rows(
                connection,
                "profile_automation_scope",
                ("profile_id", "automation_group_id", "consent_state", "revision"),
            ),
            "plans": _table_rows(
                connection,
                "profile_daily_plans",
                (
                    "plan_id",
                    "profile_id",
                    "business_date",
                    "role",
                    "sampled_limit",
                    "target",
                    "work_group_id",
                    "version_id",
                    "status",
                    "warning",
                ),
            ),
        }
        from app.services.legacy_daily_budget import inspect_legacy_daily_budgets

        legacy_budget = [
            finding.as_dict()
            for finding in inspect_legacy_daily_budgets(
                connection, business_date
            )
        ]
    return {
        "business_date": business_date,
        "library": library,
        "tables": tables,
        "legacy_budget": legacy_budget,
        "policy": {key: m.get_setting(key) for key in _READINESS_POLICY_KEYS},
    }


def _readiness_revision(snapshot: dict[str, object] | None = None) -> str:
    payload = json.dumps(
        snapshot if snapshot is not None else _readiness_snapshot(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _preview_profile_selection(snapshot: dict[str, object]) -> tuple[list[int], list[int]]:
    tables = snapshot["tables"]
    if not isinstance(tables, dict):
        return [], []
    groups = tables.get("groups", [])
    profiles = tables.get("profiles", [])
    links = tables.get("group_profiles", [])
    if not isinstance(groups, list) or not isinstance(profiles, list) or not isinstance(links, list):
        return [], []
    active_groups = {
        int(row["id"])
        for row in groups
        if isinstance(row, dict) and int(row.get("is_active") or 0) == 1
    }
    active_profiles = {
        int(row["id"])
        for row in profiles
        if isinstance(row, dict) and str(row.get("status") or "") == "active"
    }
    selected_profiles = {
        int(row["profile_id"])
        for row in links
        if isinstance(row, dict)
        and int(row.get("is_enabled") or 0) == 1
        and int(row.get("group_id")) in active_groups
        and int(row.get("profile_id")) in active_profiles
    }
    return sorted(active_groups), sorted(selected_profiles)


def _readiness_feasibility(snapshot: dict[str, object]) -> dict[str, object]:
    """Estimate today's minimum-paced capacity without changing local state."""
    tables = snapshot.get("tables", {})
    policy = snapshot.get("policy", {})
    if not isinstance(tables, dict) or not isinstance(policy, dict):
        return {"state": "unavailable", "planned_slots": 0, "shortfall": 0}
    business_date = str(snapshot.get("business_date") or "")
    plans = tables.get("plans", [])
    if not isinstance(plans, list):
        return {"state": "unavailable", "planned_slots": 0, "shortfall": 0}
    planned_slots = sum(
        max(0, int(row.get("target") or 0))
        for row in plans
        if isinstance(row, dict)
        and row.get("business_date") == business_date
        and str(row.get("status") or "") not in {"expired", "cancelled"}
    )
    if planned_slots == 0:
        return {"state": "no_plan_work", "planned_slots": 0, "shortfall": 0}

    enabled = str(policy.get("human_rhythm_enabled") or "1").lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return {
            "state": "unbounded",
            "planned_slots": planned_slots,
            "shortfall": 0,
        }
    try:
        day = date.fromisoformat(business_date)
        now = m._local_now()
    except (TypeError, ValueError):
        return {"state": "unavailable", "planned_slots": planned_slots, "shortfall": 0}
    if now.date() != day:
        return {
            "state": "date_changed",
            "planned_slots": planned_slots,
            "shortfall": 0,
        }
    window_key = "send_windows_weekend" if day.weekday() >= 5 else "send_windows_weekday"
    windows = m._parse_send_windows(str(policy.get(window_key) or ""))
    if not windows:
        return {
            "state": "unbounded",
            "planned_slots": planned_slots,
            "shortfall": 0,
        }
    try:
        delay_min = float(policy.get("delay_min_sec") or 60)
        delay_max = float(policy.get("delay_max_sec") or 180)
    except (TypeError, ValueError):
        delay_min, delay_max = 60.0, 180.0
    mandatory_floor = max(5.0, min(delay_min, delay_max))
    capacity = 0
    for start, end in windows:
        window_start = datetime.combine(day, start)
        window_end = datetime.combine(day, end)
        if window_end <= now:
            continue
        available_from = max(window_start, now)
        seconds = (window_end - available_from).total_seconds()
        if seconds > 0:
            capacity += ceil(seconds / mandatory_floor)
    shortfall = max(0, planned_slots - capacity)
    return {
        "state": "shortfall" if shortfall else "fits_minimum_pacing",
        "planned_slots": planned_slots,
        "minimum_capacity": capacity,
        "minimum_delay_sec": mandatory_floor,
        "shortfall": shortfall,
    }


@router.post("/api/campaign/preview")
async def campaign_preview():
    """Return read-only readiness; no roles, limits, plans or SDK calls are created."""
    snapshot = _readiness_snapshot()
    revision = _readiness_revision(snapshot)
    messages = m.load_message_pool()
    library = snapshot.get("library", {})
    library_available = bool(messages) or (
        isinstance(library, dict) and bool(library.get("version_id"))
    )
    group_ids, profile_ids = _preview_profile_selection(snapshot)
    hold_state, hold_active = recovery_hold.external_actions_status()
    legacy_budget = snapshot.get("legacy_budget", [])
    migration_review = [
        row
        for row in legacy_budget
        if isinstance(row, dict)
        and row.get("status") == "MIGRATION_REVIEW_REQUIRED"
    ]
    checks = {
        "library": library_available,
        "groups": bool(group_ids),
        "profiles": bool(profile_ids),
    }
    blockers = tuple(
        code
        for code, active in (
            ("recovery_hold_active", hold_active),
            (f"max_authorization_{hold_state}", hold_state != "authorized" and not hold_active),
            ("migration_review_required", bool(migration_review)),
        )
        if active
    )
    feasibility = _readiness_feasibility(snapshot)
    feasibility_warnings = (
        ("daily_plan_window_shortfall",)
        if feasibility.get("state") == "shortfall"
        else ()
    )
    warnings = (
        ("daily_plans_materialize_on_start",)
        if not any(
            isinstance(row, dict)
            and row.get("business_date") == snapshot["business_date"]
            for row in snapshot.get("tables", {}).get("plans", [])
        )
        else ()
    )
    report = build_readiness(
        version=str(getattr(m, "APP_VERSION", "unknown")),
        scope=_campaign_scope(),
        checks=checks,
        blockers=blockers,
        warnings=warnings + feasibility_warnings,
        selection={
            "groups": group_ids,
            "profiles": profile_ids,
            "library_count": int(library.get("item_count", len(messages)))
            if isinstance(library, dict)
            else len(messages),
            "daily_limit_range": list(m._daily_limit_bounds()),
            "business_date": snapshot["business_date"],
            "external_actions": hold_state,
            "migration": {
                "state": "review_required" if migration_review else "ready",
                "profiles": [int(row["profile_id"]) for row in migration_review],
            },
            "feasibility": feasibility,
        },
    )
    return {
        "ok": report.ready,
        "state": "ready" if report.ready else "blocked",
        "version": report.version,
        "scope": report.scope,
        "checks": report.checks,
        "blockers": list(report.blockers),
        "warnings": list(report.warnings),
        "selection": report.selection,
        "readiness_revision": revision,
    }


def _require_fresh_preview(body: CampaignStartIn | None) -> None:
    if body is None or body.readiness_revision is None:
        return
    current = _readiness_revision()
    if not hmac.compare_digest(body.readiness_revision, current):
        raise HTTPException(
            409,
            {
                "code": "PREVIEW_STALE",
                "message": "Предпросмотр устарел. Обновите readiness перед Стартом.",
                "readiness_revision": current,
            },
        )


@router.post("/api/campaign/start")
async def campaign_start(
    body: CampaignStartIn | None = None,
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
):

    recovery_hold.require_external_actions_released()
    _require_fresh_preview(body)
    from app.campaign_worker import legacy_budget_migration_report

    migration_review = [
        row
        for row in legacy_budget_migration_report()
        if row.get("status") == "MIGRATION_REVIEW_REQUIRED"
    ]
    if migration_review:
        raise HTTPException(
            409,
            {
                "code": "MIGRATION_REVIEW_REQUIRED",
                "profiles": [int(row["profile_id"]) for row in migration_review],
            },
        )
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
    if pending.replayed and pending.state == "preflight":
        return {
            "ok": True,
            "state": pending.state,
            "generation": pending.generation,
            "pending": True,
        }
    if pending.state == "running":
        return {
            "ok": True,
            "state": pending.state,
            "generation": pending.generation,
            "campaign_id": m.RUNTIME.current_campaign_id,
        }
    from app.campaign_worker import materialize_daily_plans

    try:
        # Pin the account-day plan before route preflight. A temporary proxy
        # failure must block external work without losing today's allocation.
        async with REGISTRY.app.message_pool_lock:
            materialize_daily_plans()
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
    try:
        started = await m._start_worker(
            control_generation=running.generation,
            preflight=False,
        )
    except Exception:
        coordinator.fail_start(command_id)
        m.set_setting("auto_run", "0")
        raise
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
    intent = await asyncio.to_thread(_persist_stop_intent, command_id)
    if intent.state == "stopped":
        return {"ok": True, "state": intent.state, "generation": intent.generation}
    await asyncio.to_thread(m.set_setting, "auto_run", "0")
    await m._stop_worker(finish_status="stopped", reason="Остановлено пользователем")
    completed = await asyncio.to_thread(
        _persist_stop_completion, command_id, "stopped"
    )
    return {"ok": True, "state": completed.state, "generation": completed.generation}


@router.post("/api/campaign/pause")
async def campaign_pause(
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
):

    command_id = _request_id(request_id)
    intent = await asyncio.to_thread(_persist_stop_intent, command_id)
    if intent.state == "stopped":
        return {"ok": True, "state": intent.state, "generation": intent.generation}
    await asyncio.to_thread(m.set_setting, "auto_run", "0")
    await m._stop_worker(finish_status="paused", reason="Пауза")
    completed = await asyncio.to_thread(
        _persist_stop_completion, command_id, "paused"
    )
    await asyncio.to_thread(m.append_log, "Рассылка на паузе")
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
async def campaign_test(
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
):

    recovery_hold.require_external_actions_released()
    m._require_vault_unlocked()
    if m.RUNTIME.worker_busy():
        raise HTTPException(409, "кампания идёт")
    command_id = _request_id(request_id)
    coordinator = _coordinator()
    intent = coordinator.begin_test(command_id)
    if intent.replayed and intent.accepted:
        if intent.state == "testing":
            raise HTTPException(409, {"state": intent.state, "pending": True})
        return {
            "ok": True,
            "state": intent.state,
            "generation": intent.generation,
            "control_state": intent.state,
            "idempotent": True,
        }
    if not intent.accepted:
        raise HTTPException(409, {"state": intent.state, "blockers": intent.payload})

    daily_job = None
    daily_finalized = False
    profile = None
    group = None
    text = ""
    from app.campaign_send import DailyReservationUnavailable, SendTracker

    tracker = SendTracker()
    try:
        # Publication and test selection share one short process-local lock.
        # The lock is released before proxy/provider work begins; the selected
        # daily slot or legacy text remains pinned for this command.
        async with REGISTRY.app.message_pool_lock:
            messages = m.load_message_pool()
            if not _library_available(messages):
                raise HTTPException(400, "Нет сообщений")
            groups = m._active_groups()
            if not groups:
                raise HTTPException(400, "Нет групп")
            if _library_available(messages):
                from app.campaign_worker import _claim_daily_job_sync

                daily_candidate = _claim_daily_job_sync()
                if isinstance(daily_candidate, dict):
                    daily_job = daily_candidate
                elif daily_candidate in {"DAILY_WAIT", "DAILY_DONE"}:
                    raise HTTPException(409, "Нет доступного дневного slot")
            if daily_job is not None:
                profile = daily_job["profile"]
                group = daily_job["group"]
            else:
                for candidate_group in groups:
                    profiles = m._active_profiles_for_group(candidate_group["id"])
                    for candidate_profile in profiles:
                        if m._is_circuit_open(candidate_profile["id"]):
                            continue
                        if m._can_send_in_group(
                            candidate_profile, candidate_group["id"]
                        ):
                            profile, group = candidate_profile, candidate_group
                            break
                    if profile:
                        break
            if not profile or not group:
                raise HTTPException(400, "Нет активного профиля для теста")
            text = daily_job["text"] if daily_job is not None else messages[0]

        m._require_profile_runtime_available(int(profile["id"]))
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
        if daily_job is not None:
            from app.campaign_worker import _finalize_daily_job

            _finalize_daily_job(daily_job, ok, tracker)
            daily_finalized = True
        if not ok:
            if tracker.error == DailyReservationUnavailable.code:
                raise HTTPException(409, "Нет доступного дневного бюджета")
            raise HTTPException(502, "Тест не удался — смотрите лог / нужен повторный вход")
        completed = coordinator.complete_test(command_id)
        if not completed.accepted:
            raise HTTPException(409, {"state": completed.state})
        m.append_log(f"Тест отправки успешен #{profile['id']} → «{group['name']}»")
        return {
            "ok": True,
            "profile_id": profile["id"],
            "phone": profile["phone"],
            "group_id": group["id"],
            "text_preview": text[:80],
            "control_state": completed.state,
        }
    except BaseException:
        if daily_job is not None and not daily_finalized:
            from app.campaign_worker import _finalize_daily_job

            _finalize_daily_job(daily_job, False, tracker)
        coordinator.fail_test(command_id)
        raise


@router.get("/api/campaigns")
async def list_campaigns(limit: int = 50):

    limit = min(max(limit, 1), 200)
    with m._conn() as c:
        rows = c.execute(
            "SELECT * FROM campaigns ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"items": [dict(r) for r in rows]}
