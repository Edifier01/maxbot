"""Durable storage for logical campaign operations and network attempts.

The repository deliberately knows nothing about MAX or retry policy.  It only
provides transactional state transitions so the service layer can make a
conservative decision after a process crash.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator


OPERATION_STATUSES = frozenset(
    {"reserved", "claimed", "in_flight", "accepted", "failed_unsent", "unknown"}
)
TERMINAL_STATUSES = frozenset({"accepted", "unknown"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class OperationRecord:
    operation_id: str
    scope: str
    profile_id: int
    group_id: int | None
    text: str
    status: str
    provider_message_id: str
    budget_date: str | None
    budget_occupied: bool
    pre_effect_retry_count: int
    max_pre_effect_retries: int
    attempt_count: int
    active_attempt_no: int | None
    last_error: str
    daily_plan_id: str | None
    slot_id: str | None
    route_snapshot: dict[str, object]

    @property
    def retryable(self) -> bool:
        return self.status in {"reserved", "claimed", "failed_unsent"}


class OperationRepository:
    """SQLite repository with explicit transactional operation transitions."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        if self.connection.row_factory is None:
            self.connection.row_factory = sqlite3.Row
        self.ensure_schema(self.connection)

    @staticmethod
    def ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS operations (
                operation_id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                profile_id INTEGER NOT NULL,
                group_id INTEGER,
                text TEXT NOT NULL,
                text_sha256 TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN (
                    'reserved', 'claimed', 'in_flight', 'accepted',
                    'failed_unsent', 'unknown'
                )),
                provider_message_id TEXT NOT NULL DEFAULT '',
                budget_date TEXT,
                daily_plan_id TEXT,
                slot_id TEXT,
                route_snapshot_json TEXT NOT NULL DEFAULT '{}',
                budget_occupied INTEGER NOT NULL DEFAULT 1,
                pre_effect_retry_count INTEGER NOT NULL DEFAULT 0,
                max_pre_effect_retries INTEGER NOT NULL DEFAULT 2,
                last_error TEXT NOT NULL DEFAULT '',
                retry_after_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operation_attempts (
                operation_id TEXT NOT NULL REFERENCES operations(operation_id),
                attempt_no INTEGER NOT NULL,
                network_attempt_id TEXT NOT NULL UNIQUE,
                state TEXT NOT NULL CHECK(state IN (
                    'in_flight', 'accepted', 'failed_unsent', 'unknown'
                )),
                route_snapshot_json TEXT NOT NULL DEFAULT '{}',
                started_at TEXT NOT NULL,
                finalized_at TEXT,
                provider_message_id TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (operation_id, attempt_no)
            );
            CREATE TABLE IF NOT EXISTS operation_accounting (
                operation_id TEXT PRIMARY KEY REFERENCES operations(operation_id),
                effect_kind TEXT NOT NULL,
                provider_message_id TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS command_receipts (
                scope TEXT NOT NULL,
                request_id TEXT NOT NULL,
                command TEXT NOT NULL,
                operation_id TEXT NOT NULL REFERENCES operations(operation_id),
                created_at TEXT NOT NULL,
                PRIMARY KEY (scope, request_id, command)
            );
            CREATE INDEX IF NOT EXISTS idx_operations_recovery
                ON operations(status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_operations_budget
                ON operations(scope, profile_id, budget_date, status);
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

    def create(
        self,
        *,
        scope: str,
        profile_id: int,
        group_id: int | None,
        text: str,
        operation_id: str | None,
        request_id: str | None,
        command: str | None,
        budget_date: str | None,
        daily_plan_id: str | None,
        slot_id: str | None,
        route_snapshot: dict[str, object] | None,
        max_pre_effect_retries: int,
        reservation_guard: Callable[[sqlite3.Connection], None] | None = None,
    ) -> OperationRecord:
        if request_id is not None and command is None:
            raise ValueError("command is required with request_id")
        if command is not None and request_id is None:
            raise ValueError("request_id is required with command")
        now = _now()
        op_id = operation_id or f"op-{uuid.uuid4().hex}"
        encoded_route = json.dumps(route_snapshot or {}, sort_keys=True)
        with self._transaction() as connection:
            if request_id is not None and command is not None:
                receipt = connection.execute(
                    "SELECT operation_id FROM command_receipts "
                    "WHERE scope=? AND request_id=? AND command=?",
                    (scope, request_id, command),
                ).fetchone()
                if receipt is not None:
                    return self._get_locked(str(receipt["operation_id"]))
            if not str(scope).strip():
                raise ValueError("scope is required")
            if int(profile_id) <= 0:
                raise ValueError("profile_id must be positive")
            if not str(text):
                raise ValueError("text is required")
            if int(max_pre_effect_retries) < 0:
                raise ValueError("max_pre_effect_retries must not be negative")
            if reservation_guard is not None:
                reservation_guard(connection)
            try:
                connection.execute(
                    """
                    INSERT INTO operations (
                        operation_id, scope, profile_id, group_id, text,
                        text_sha256, status, budget_date, daily_plan_id, slot_id,
                        route_snapshot_json, budget_occupied,
                        max_pre_effect_retries, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'reserved', ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        op_id,
                        scope,
                        int(profile_id),
                        group_id,
                        text,
                        hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        budget_date,
                        daily_plan_id,
                        slot_id,
                        encoded_route,
                        int(max_pre_effect_retries),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("operation_id already exists") from exc
            if request_id is not None and command is not None:
                connection.execute(
                    "INSERT INTO command_receipts "
                    "(scope, request_id, command, operation_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (scope, request_id, command, op_id, now),
                )
            return self._get_locked(op_id)

    def get(self, operation_id: str) -> OperationRecord | None:
        row = self.connection.execute(
            "SELECT * FROM operations WHERE operation_id=?", (operation_id,)
        ).fetchone()
        return self._record(row) if row is not None else None

    def find_retryable_for_slot(
        self, slot_id: str, *, profile_id: int, text: str
    ) -> OperationRecord | None:
        row = self.connection.execute(
            "SELECT * FROM operations WHERE slot_id=? AND profile_id=? "
            "AND text=? AND status IN ('reserved', 'claimed', 'failed_unsent') "
            "ORDER BY created_at DESC LIMIT 1",
            (slot_id, int(profile_id), text),
        ).fetchone()
        return self._record(row) if row is not None else None

    def claim(self, operation_id: str, *, profile_id: int) -> OperationRecord:
        with self._transaction():
            row = self._get_locked(operation_id)
            self._check_profile(row, profile_id)
            if row.status == "reserved":
                self.connection.execute(
                    "UPDATE operations SET status='claimed', updated_at=? "
                    "WHERE operation_id=? AND status='reserved'",
                    (_now(), operation_id),
                )
            elif row.status == "claimed":
                pass
            elif row.status in TERMINAL_STATUSES:
                raise RuntimeError(f"operation is terminal: {row.status}")
            elif row.status == "in_flight":
                raise RuntimeError("operation is already in flight")
            else:
                raise RuntimeError(f"operation must be retried explicitly: {row.status}")
            return self._get_locked(operation_id)

    def mark_in_flight(
        self,
        operation_id: str,
        *,
        route_snapshot: dict[str, object] | None,
    ) -> OperationRecord:
        with self._transaction():
            row = self._get_locked(operation_id)
            if row.status == "in_flight":
                return row
            if row.status != "claimed":
                raise RuntimeError(f"operation is not claimable: {row.status}")
            max_row = self.connection.execute(
                "SELECT MAX(attempt_no) AS max_no FROM operation_attempts "
                "WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            attempt_no = int(max_row["max_no"] or 0) + 1
            now = _now()
            route_json = json.dumps(route_snapshot or row.route_snapshot, sort_keys=True)
            self.connection.execute(
                """
                INSERT INTO operation_attempts (
                    operation_id, attempt_no, network_attempt_id, state,
                    route_snapshot_json, started_at
                ) VALUES (?, ?, ?, 'in_flight', ?, ?)
                """,
                (
                    operation_id,
                    attempt_no,
                    f"attempt-{uuid.uuid4().hex}",
                    route_json,
                    now,
                ),
            )
            self.connection.execute(
                "UPDATE operations SET status='in_flight', route_snapshot_json=?, "
                "updated_at=? WHERE operation_id=?",
                (route_json, now, operation_id),
            )
            return self._get_locked(operation_id)

    def mark_failed_unsent(self, operation_id: str, error: str) -> OperationRecord:
        with self._transaction():
            row = self._get_locked(operation_id)
            if row.status in TERMINAL_STATUSES:
                return row
            if row.status == "in_flight":
                raise RuntimeError("in-flight operation cannot be marked unsent")
            if row.status not in {"reserved", "claimed", "failed_unsent"}:
                raise RuntimeError(f"operation is not pre-send: {row.status}")
            self.connection.execute(
                "UPDATE operations SET status='failed_unsent', last_error=?, updated_at=? "
                "WHERE operation_id=?",
                (str(error)[:500], _now(), operation_id),
            )
            return self._get_locked(operation_id)

    def retry(self, operation_id: str, *, proof_no_send: bool) -> OperationRecord:
        with self._transaction():
            row = self._get_locked(operation_id)
            if not proof_no_send:
                raise RuntimeError("explicit proof_no_send is required")
            if row.status != "failed_unsent":
                raise RuntimeError(f"operation is not safely retryable: {row.status}")
            if row.pre_effect_retry_count >= row.max_pre_effect_retries:
                raise RuntimeError("pre-effect retry budget exhausted")
            self.connection.execute(
                "UPDATE operations SET status='claimed', pre_effect_retry_count="
                "pre_effect_retry_count+1, updated_at=? WHERE operation_id=?",
                (_now(), operation_id),
            )
            return self._get_locked(operation_id)

    def mark_unknown(self, operation_id: str, error: str) -> OperationRecord:
        with self._transaction():
            row = self._get_locked(operation_id)
            if row.status == "accepted":
                return row
            if row.status == "unknown":
                return row
            if row.status != "in_flight":
                raise RuntimeError(f"only in-flight operation can become unknown: {row.status}")
            now = _now()
            attempt = self.connection.execute(
                "SELECT attempt_no FROM operation_attempts WHERE operation_id=? "
                "ORDER BY attempt_no DESC LIMIT 1",
                (operation_id,),
            ).fetchone()
            if attempt is not None:
                self.connection.execute(
                    "UPDATE operation_attempts SET state='unknown', finalized_at=?, "
                    "error=? WHERE operation_id=? AND attempt_no=?",
                    (now, str(error)[:500], operation_id, attempt["attempt_no"]),
                )
            self.connection.execute(
                "UPDATE operations SET status='unknown', last_error=?, updated_at=? "
                "WHERE operation_id=?",
                (str(error)[:500], now, operation_id),
            )
            return self._get_locked(operation_id)

    def mark_accepted(
        self, operation_id: str, *, provider_message_id: str
    ) -> OperationRecord:
        provider_id = str(provider_message_id).strip()
        if not provider_id:
            raise ValueError("provider_message_id is required")
        with self._transaction():
            row = self._get_locked(operation_id)
            if row.status == "accepted":
                if row.provider_message_id != provider_id:
                    raise RuntimeError("accepted provider id is immutable")
                return row
            if row.status != "in_flight":
                raise RuntimeError(f"only in-flight operation can be accepted: {row.status}")
            now = _now()
            attempt = self.connection.execute(
                "SELECT attempt_no FROM operation_attempts WHERE operation_id=? "
                "ORDER BY attempt_no DESC LIMIT 1",
                (operation_id,),
            ).fetchone()
            if attempt is None:
                raise RuntimeError("accepted operation has no network attempt")
            attempt_no = int(attempt["attempt_no"])
            self.connection.execute(
                "UPDATE operation_attempts SET state='accepted', finalized_at=?, "
                "provider_message_id=? WHERE operation_id=? AND attempt_no=?",
                (now, provider_id, operation_id, attempt_no),
            )
            self.connection.execute(
                "UPDATE operations SET status='accepted', provider_message_id=?, "
                "last_error='', updated_at=? WHERE operation_id=?",
                (provider_id, now, operation_id),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO operation_accounting "
                "(operation_id, effect_kind, provider_message_id, applied_at) "
                "VALUES (?, 'send_accepted', ?, ?)",
                (operation_id, provider_id, now),
            )
            return self._get_locked(operation_id)

    def recover_in_flight(self) -> list[str]:
        rows = self.connection.execute(
            "SELECT operation_id FROM operations WHERE status='in_flight' "
            "ORDER BY operation_id"
        ).fetchall()
        recovered: list[str] = []
        for row in rows:
            self.mark_unknown(
                str(row["operation_id"]), "recovered abandoned in-flight operation"
            )
            recovered.append(str(row["operation_id"]))
        return recovered

    def _get_locked(self, operation_id: str) -> OperationRecord:
        row = self.connection.execute(
            "SELECT * FROM operations WHERE operation_id=?", (operation_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"operation not found: {operation_id}")
        return self._record(row)

    @staticmethod
    def _check_profile(row: OperationRecord, profile_id: int) -> None:
        if int(profile_id) != row.profile_id:
            raise ValueError("operation belongs to a different profile")

    def _record(self, row: sqlite3.Row) -> OperationRecord:
        attempt = self.connection.execute(
            "SELECT MAX(attempt_no) AS max_no, COUNT(*) AS count FROM operation_attempts "
            "WHERE operation_id=?",
            (row["operation_id"],),
        ).fetchone()
        try:
            route = json.loads(row["route_snapshot_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            route = {}
        if not isinstance(route, dict):
            route = {}
        return OperationRecord(
            operation_id=str(row["operation_id"]),
            scope=str(row["scope"]),
            profile_id=int(row["profile_id"]),
            group_id=int(row["group_id"]) if row["group_id"] is not None else None,
            text=str(row["text"]),
            status=str(row["status"]),
            provider_message_id=str(row["provider_message_id"] or ""),
            budget_date=(
                str(row["budget_date"]) if row["budget_date"] is not None else None
            ),
            budget_occupied=bool(row["budget_occupied"]),
            pre_effect_retry_count=int(row["pre_effect_retry_count"]),
            max_pre_effect_retries=int(row["max_pre_effect_retries"]),
            attempt_count=int(attempt["count"]),
            active_attempt_no=(
                int(attempt["max_no"]) if attempt["max_no"] is not None else None
            ),
            last_error=str(row["last_error"] or ""),
            daily_plan_id=(
                str(row["daily_plan_id"]) if row["daily_plan_id"] is not None else None
            ),
            slot_id=str(row["slot_id"]) if row["slot_id"] is not None else None,
            route_snapshot=route,
        )
