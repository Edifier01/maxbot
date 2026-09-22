"""Durable account-day plans and immutable personal message slots."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class DailyPlanRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        if self.connection.row_factory is None:
            self.connection.row_factory = sqlite3.Row
        self.ensure_schema(connection)

    @staticmethod
    def ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS daily_cycles (
                scope TEXT NOT NULL,
                business_date TEXT NOT NULL,
                cycle_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (scope, business_date)
            );
            CREATE TABLE IF NOT EXISTS profile_daily_plans (
                scope TEXT NOT NULL,
                plan_id TEXT NOT NULL UNIQUE,
                profile_id INTEGER NOT NULL,
                business_date TEXT NOT NULL,
                role TEXT NOT NULL,
                sampled_limit INTEGER NOT NULL,
                quiet_limit INTEGER NOT NULL,
                target INTEGER NOT NULL,
                work_group_id INTEGER,
                version_id TEXT,
                status TEXT NOT NULL,
                warning TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                PRIMARY KEY (scope, profile_id, business_date)
            );
            CREATE TABLE IF NOT EXISTS profile_message_slots (
                slot_id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                plan_id TEXT NOT NULL REFERENCES profile_daily_plans(plan_id),
                ordinal INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                pass_index INTEGER NOT NULL,
                version_id TEXT,
                rendered_text TEXT NOT NULL,
                status TEXT NOT NULL,
                failure_reason TEXT NOT NULL DEFAULT '',
                retry_count INTEGER NOT NULL DEFAULT 0,
                claimed_at TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE (plan_id, ordinal)
            );
            CREATE INDEX IF NOT EXISTS idx_daily_plan_claim
                ON profile_message_slots(scope, status, updated_at);
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

    def create_plan(
        self,
        *,
        scope: str,
        profile_id: int,
        business_date: str,
        role: str,
        sampled_limit: int,
        quiet_limit: int,
        target: int,
        work_group_id: int | None,
        version_id: str | None,
        warning: str,
        slots: tuple[dict[str, object], ...],
    ):
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT plan_id FROM profile_daily_plans "
                "WHERE scope=? AND profile_id=? AND business_date=?",
                (scope, profile_id, business_date),
            ).fetchone()
            if existing is not None:
                return self.get_plan(scope, profile_id, business_date)
            cycle = connection.execute(
                "SELECT cycle_id FROM daily_cycles WHERE scope=? AND business_date=?",
                (scope, business_date),
            ).fetchone()
            if cycle is None:
                connection.execute(
                    "INSERT INTO daily_cycles(scope, business_date, cycle_id, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (scope, business_date, f"cycle-{uuid.uuid4().hex}", _now()),
                )
            plan_id = f"plan-{uuid.uuid4().hex}"
            now = _now()
            status = "waiting_pool" if warning == "POOL_EMPTY" else "active"
            connection.execute(
                """
                INSERT INTO profile_daily_plans (
                    scope, plan_id, profile_id, business_date, role,
                    sampled_limit, quiet_limit, target, work_group_id, version_id,
                    status, warning, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope,
                    plan_id,
                    profile_id,
                    business_date,
                    role,
                    sampled_limit,
                    quiet_limit,
                    target,
                    work_group_id,
                    version_id,
                    status,
                    warning,
                    now,
                ),
            )
            connection.executemany(
                """
                INSERT INTO profile_message_slots (
                    slot_id, scope, plan_id, ordinal, item_id, pass_index,
                    version_id, rendered_text, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)
                """,
                [
                    (
                        f"slot-{uuid.uuid4().hex}",
                        scope,
                        plan_id,
                        index,
                        slot["item_id"],
                        slot["pass_index"],
                        slot["version_id"],
                        slot["rendered_text"],
                        now,
                    )
                    for index, slot in enumerate(slots)
                ],
            )
        return self.get_plan(scope, profile_id, business_date)

    def get_plan(self, scope: str, profile_id: int, business_date: str):
        plan = self.connection.execute(
            "SELECT * FROM profile_daily_plans WHERE scope=? AND profile_id=? "
            "AND business_date=?",
            (scope, profile_id, business_date),
        ).fetchone()
        if plan is None:
            return None
        slots = self.connection.execute(
            "SELECT * FROM profile_message_slots WHERE plan_id=? ORDER BY ordinal",
            (plan["plan_id"],),
        ).fetchall()
        return plan, tuple(slots)

    def fill_waiting_plan(
        self,
        *,
        scope: str,
        profile_id: int,
        business_date: str,
        version_id: str,
        slots: tuple[dict[str, object], ...],
    ):
        """Fill a POOL_EMPTY plan once; never change its sampled target/owner."""

        with self._transaction() as connection:
            plan = connection.execute(
                "SELECT * FROM profile_daily_plans WHERE scope=? AND profile_id=? "
                "AND business_date=?",
                (scope, profile_id, business_date),
            ).fetchone()
            if plan is None:
                raise KeyError("daily plan not found")
            existing_slots = connection.execute(
                "SELECT COUNT(*) AS n FROM profile_message_slots WHERE plan_id=?",
                (plan["plan_id"],),
            ).fetchone()
            if plan["warning"] != "POOL_EMPTY" or int(existing_slots["n"]) != 0:
                return self.get_plan(scope, profile_id, business_date)
            now = _now()
            connection.execute(
                "UPDATE profile_daily_plans SET version_id=?, status='active', warning='' "
                "WHERE plan_id=? AND warning='POOL_EMPTY'",
                (version_id, plan["plan_id"]),
            )
            connection.executemany(
                """
                INSERT INTO profile_message_slots (
                    slot_id, scope, plan_id, ordinal, item_id, pass_index,
                    version_id, rendered_text, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)
                """,
                [
                    (
                        f"slot-{uuid.uuid4().hex}",
                        scope,
                        plan["plan_id"],
                        index,
                        slot["item_id"],
                        slot["pass_index"],
                        slot["version_id"],
                        slot["rendered_text"],
                        now,
                    )
                    for index, slot in enumerate(slots)
                ],
            )
        return self.get_plan(scope, profile_id, business_date)

    def get_slot(self, slot_id: str):
        return self.connection.execute(
            "SELECT s.*, p.profile_id, p.work_group_id, p.business_date "
            "FROM profile_message_slots s JOIN profile_daily_plans p ON p.plan_id=s.plan_id "
            "WHERE s.slot_id=?",
            (slot_id,),
        ).fetchone()

    def claim_next(
        self,
        scope: str,
        business_date: str,
        *,
        eligible_assignments: tuple[tuple[int, int], ...] | None = None,
    ):
        with self._transaction() as connection:
            clauses = [
                "s.scope=?",
                "p.business_date=?",
                "s.status='queued'",
                "p.status='active'",
            ]
            params: list[object] = [scope, business_date]
            if eligible_assignments is not None:
                if not eligible_assignments:
                    return None
                clauses.append(
                    "(" + " OR ".join(
                        "p.profile_id=? AND p.work_group_id=?"
                        for _ in eligible_assignments
                    ) + ")"
                )
                for profile_id, group_id in eligible_assignments:
                    params.extend((int(profile_id), int(group_id)))
            row = connection.execute(
                f"""
                SELECT s.slot_id
                FROM profile_message_slots s
                JOIN profile_daily_plans p ON p.plan_id=s.plan_id
                WHERE {' AND '.join(clauses)}
                ORDER BY p.created_at, p.profile_id, s.ordinal
                LIMIT 1
                """,
                params,
            ).fetchone()
            if row is None:
                return None
            now = _now()
            connection.execute(
                "UPDATE profile_message_slots SET status='claimed', claimed_at=?, "
                "updated_at=? WHERE slot_id=? AND status='queued'",
                (now, now, row["slot_id"]),
            )
        return self.get_slot(str(row["slot_id"]))

    def mark_unknown(self, slot_id: str, reason: str):
        with self._transaction() as connection:
            row = self.get_slot(slot_id)
            if row is None:
                raise KeyError("slot not found")
            if row["status"] == "unknown":
                return row
            if row["status"] == "accepted":
                return row
            if row["status"] not in {"claimed", "in_flight"}:
                raise RuntimeError("slot is not externally ambiguous")
            connection.execute(
                "UPDATE profile_message_slots SET status='unknown', failure_reason=?, "
                "updated_at=? WHERE slot_id=?",
                (str(reason)[:500], _now(), slot_id),
            )
        return self.get_slot(slot_id)

    def mark_failed_unsent(self, slot_id: str, reason: str):
        with self._transaction() as connection:
            row = self.get_slot(slot_id)
            if row is None:
                raise KeyError("slot not found")
            if row["status"] == "failed_unsent":
                return row
            if row["status"] == "accepted":
                return row
            if row["status"] not in {"claimed", "in_flight"}:
                raise RuntimeError("slot is not currently claimed")
            connection.execute(
                "UPDATE profile_message_slots SET status='failed_unsent', "
                "failure_reason=?, updated_at=? WHERE slot_id=?",
                (str(reason)[:500], _now(), slot_id),
            )
        return self.get_slot(slot_id)

    def mark_accepted(self, slot_id: str):
        with self._transaction() as connection:
            row = self.get_slot(slot_id)
            if row is None:
                raise KeyError("slot not found")
            if row["status"] == "accepted":
                return row
            if row["status"] not in {"claimed", "in_flight"}:
                raise RuntimeError("slot is not claimable")
            connection.execute(
                "UPDATE profile_message_slots SET status='accepted', updated_at=? "
                "WHERE slot_id=?",
                (_now(), slot_id),
            )
        return self.get_slot(slot_id)

    def retry(self, slot_id: str, *, proof_no_send: bool):
        if not proof_no_send:
            raise RuntimeError("explicit proof_no_send is required")
        with self._transaction() as connection:
            row = self.get_slot(slot_id)
            if row is None:
                raise KeyError("slot not found")
            if row["status"] not in {"claimed", "failed_unsent"}:
                raise RuntimeError("slot is not safely retryable")
            connection.execute(
                "UPDATE profile_message_slots SET status='queued', retry_count=retry_count+1, "
                "failure_reason='', updated_at=? WHERE slot_id=?",
                (_now(), slot_id),
            )
        return self.get_slot(slot_id)

    def expire_before(self, scope: str, business_date: str) -> int:
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE profile_message_slots SET status='expired', "
                "failure_reason='date_expired', updated_at=? WHERE scope=? "
                "AND status='queued' AND plan_id IN ("
                "SELECT plan_id FROM profile_daily_plans WHERE business_date < ?)",
                (_now(), scope, business_date),
            )
            return int(cursor.rowcount)

    def count_slots(self, scope: str, status: str | None = None) -> int:
        if status is None:
            row = self.connection.execute(
                "SELECT COUNT(*) AS n FROM profile_message_slots WHERE scope=?",
                (scope,),
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT COUNT(*) AS n FROM profile_message_slots WHERE scope=? AND status=?",
                (scope, status),
            ).fetchone()
        return int(row["n"] if row else 0)
