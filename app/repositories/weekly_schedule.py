"""Persistent account weekdays, group proxy assignments and weekly send slots."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Iterator
from urllib.parse import urlsplit

import antiban_core


def _fingerprint(proxy_url: str) -> str:
    return hashlib.sha256(proxy_url.strip().encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


class WeeklyScheduleRepository:
    """Tenant-local persistent weekly plan state."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        if self.connection.row_factory is None:
            self.connection.row_factory = sqlite3.Row

    def ensure_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS profile_send_schedules (
                profile_id INTEGER PRIMARY KEY,
                send_weekday INTEGER NOT NULL CHECK(send_weekday BETWEEN 0 AND 6),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS profile_group_proxy_assignments (
                profile_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                proxy_fingerprint TEXT,
                assigned_at TEXT NOT NULL,
                PRIMARY KEY(profile_id, group_id)
            );
            CREATE INDEX IF NOT EXISTS idx_group_proxy_assignments_load
                ON profile_group_proxy_assignments(group_id, proxy_fingerprint);
            CREATE TABLE IF NOT EXISTS profile_weekly_slots (
                scope TEXT NOT NULL,
                slot_id TEXT NOT NULL UNIQUE,
                profile_id INTEGER NOT NULL,
                week_start TEXT NOT NULL,
                scheduled_date TEXT NOT NULL,
                work_group_id INTEGER NOT NULL,
                message_text TEXT NOT NULL,
                version_id TEXT,
                status TEXT NOT NULL,
                failure_reason TEXT NOT NULL DEFAULT '',
                retry_count INTEGER NOT NULL DEFAULT 0,
                claimed_at TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(scope, profile_id, week_start)
            );
            CREATE INDEX IF NOT EXISTS idx_weekly_slots_claim
                ON profile_weekly_slots(scope, scheduled_date, status, updated_at);
            CREATE TABLE IF NOT EXISTS weekly_schedule_migrations (
                migration_key TEXT PRIMARY KEY,
                completed_at TEXT NOT NULL
            );
            """
        )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        if self.connection.in_transaction:
            savepoint = f"weekly_{uuid.uuid4().hex}"
            self.connection.execute(f"SAVEPOINT {savepoint}")
            try:
                yield self.connection
            except BaseException:
                self.connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            return
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def backfill_assignments(self) -> None:
        """Assign days and proxies once, in stable profile/group order."""
        with self._transaction() as connection:
            profiles = connection.execute(
                "SELECT DISTINCT p.id FROM profiles p "
                "JOIN group_profiles gp ON gp.profile_id=p.id ORDER BY p.id"
            ).fetchall()
            for row in profiles:
                self._assign_day_locked(connection, int(row["id"]))
            groups = connection.execute(
                "SELECT DISTINCT g.id FROM groups g "
                "JOIN group_profiles gp ON gp.group_id=g.id ORDER BY g.id"
            ).fetchall()
            for row in groups:
                self._sync_group_proxy_assignments_locked(connection, int(row["id"]))

    def assign_profile(self, profile_id: int, group_id: int) -> dict[str, object]:
        with self._transaction() as connection:
            self._assign_day_locked(connection, int(profile_id))
            self._assign_group_proxy_locked(connection, int(profile_id), int(group_id))
        return self.assignment_for(profile_id, group_id) or {
            "profile_id": int(profile_id),
            "group_id": int(group_id),
            "send_weekday": None,
            "proxy_fingerprint": None,
        }

    def _assign_day_locked(self, connection: sqlite3.Connection, profile_id: int) -> int:
        existing = connection.execute(
            "SELECT send_weekday FROM profile_send_schedules WHERE profile_id=?",
            (profile_id,),
        ).fetchone()
        if existing is not None:
            return int(existing["send_weekday"])
        counts = [0] * 7
        for row in connection.execute(
            "SELECT send_weekday, COUNT(*) AS n FROM profile_send_schedules "
            "GROUP BY send_weekday ORDER BY send_weekday"
        ):
            counts[int(row["send_weekday"])] = int(row["n"])
        weekday = min(range(7), key=lambda item: (counts[item], item))
        connection.execute(
            "INSERT INTO profile_send_schedules(profile_id, send_weekday, created_at) "
            "VALUES (?, ?, ?)",
            (profile_id, weekday, _utc_now()),
        )
        return weekday

    def _assign_group_proxy_locked(
        self, connection: sqlite3.Connection, profile_id: int, group_id: int
    ) -> str | None:
        group = connection.execute(
            "SELECT proxy FROM groups WHERE id=?", (group_id,)
        ).fetchone()
        if group is None:
            return None
        proxies = self._unique_proxies(str(group["proxy"] or ""))
        by_fingerprint = {_fingerprint(proxy): proxy for proxy in proxies}
        existing = connection.execute(
            "SELECT proxy_fingerprint FROM profile_group_proxy_assignments "
            "WHERE profile_id=? AND group_id=?",
            (profile_id, group_id),
        ).fetchone()
        current = str(existing["proxy_fingerprint"] or "") if existing else ""
        if current and current in by_fingerprint:
            return current
        if not proxies:
            fingerprint = None
        else:
            counts = {key: 0 for key in by_fingerprint}
            for row in connection.execute(
                "SELECT proxy_fingerprint, COUNT(*) AS n "
                "FROM profile_group_proxy_assignments WHERE group_id=? "
                "GROUP BY proxy_fingerprint",
                (group_id,),
            ):
                key = str(row["proxy_fingerprint"] or "")
                if key in counts:
                    counts[key] = int(row["n"])
            fingerprint = min(
                by_fingerprint,
                key=lambda key: (counts[key], proxies.index(by_fingerprint[key])),
            )
        connection.execute(
            "INSERT INTO profile_group_proxy_assignments "
            "(profile_id, group_id, proxy_fingerprint, assigned_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(profile_id, group_id) DO UPDATE SET "
            "proxy_fingerprint=excluded.proxy_fingerprint, assigned_at=excluded.assigned_at",
            (profile_id, group_id, fingerprint, _utc_now()),
        )
        return fingerprint

    @staticmethod
    def _unique_proxies(raw: str) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for proxy in antiban_core.parse_proxy_list(raw):
            fingerprint = _fingerprint(proxy)
            if fingerprint not in seen:
                seen.add(fingerprint)
                out.append(proxy)
        return out

    def _sync_group_proxy_assignments_locked(
        self, connection: sqlite3.Connection, group_id: int
    ) -> None:
        rows = connection.execute(
            "SELECT profile_id FROM group_profiles WHERE group_id=? "
            "ORDER BY profile_id",
            (group_id,),
        ).fetchall()
        for row in rows:
            self._assign_group_proxy_locked(connection, int(row["profile_id"]), group_id)

    def update_group_proxy_list(self, group_id: int, raw: str) -> None:
        with self._transaction() as connection:
            connection.execute("UPDATE groups SET proxy=? WHERE id=?", (raw, int(group_id)))
            self._sync_group_proxy_assignments_locked(connection, int(group_id))

    def schedule_for(self, profile_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT profile_id, send_weekday, created_at FROM profile_send_schedules "
            "WHERE profile_id=?",
            (int(profile_id),),
        ).fetchone()

    def assignment_for(self, profile_id: int, group_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT a.profile_id, a.group_id, a.proxy_fingerprint, s.send_weekday "
            "FROM profile_group_proxy_assignments a "
            "LEFT JOIN profile_send_schedules s ON s.profile_id=a.profile_id "
            "WHERE a.profile_id=? AND a.group_id=?",
            (int(profile_id), int(group_id)),
        ).fetchone()

    def assigned_proxy_url(self, profile_id: int, group_id: int) -> str | None:
        assignment = self.assignment_for(profile_id, group_id)
        fingerprint = str(assignment["proxy_fingerprint"] or "") if assignment else ""
        if not fingerprint:
            return None
        group = self.connection.execute(
            "SELECT proxy FROM groups WHERE id=?", (int(group_id),)
        ).fetchone()
        for proxy in self._unique_proxies(str(group["proxy"] or "") if group else ""):
            if _fingerprint(proxy) == fingerprint:
                return proxy
        return None

    def proxy_label_for(self, profile_id: int, group_id: int) -> str | None:
        proxy = self.assigned_proxy_url(profile_id, group_id)
        if proxy is None:
            return None
        parsed = urlsplit(proxy)
        host = parsed.hostname or "proxy"
        default_port = 1080 if parsed.scheme.lower() == "socks5" else 8080
        return f"{host}:{parsed.port or default_port}"

    def send_block_reason(
        self,
        profile_id: int,
        today: date,
        *,
        exclude_operation_id: str | None = None,
    ) -> str:
        schedule = self.schedule_for(profile_id)
        if schedule is None:
            return "unassigned"
        if int(schedule["send_weekday"]) != today.weekday():
            return "wrong_day"
        start = monday_of(today).isoformat()
        end = (monday_of(today) + timedelta(days=7)).isoformat()
        sent = self.connection.execute(
            "SELECT 1 FROM send_log WHERE profile_id=? AND status='sent' "
            "AND date(sent_at, '+3 hours')>=? AND date(sent_at, '+3 hours')<? LIMIT 1",
            (int(profile_id), start, end),
        ).fetchone()
        if sent is not None:
            return "weekly_limit"
        tables = {
            str(row["name"])
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='operations'"
            )
        }
        if "operations" in tables:
            operation_exclusion = " AND o.operation_id<>?" if exclude_operation_id else ""
            operation_params: tuple[object, ...] = (
                (int(profile_id), start, end, str(exclude_operation_id))
                if exclude_operation_id
                else (int(profile_id), start, end)
            )
            operations = self.connection.execute(
                "SELECT 1 FROM operations o WHERE o.profile_id=? AND o.budget_date>=? "
                "AND o.budget_date<? AND (o.status IN ('reserved','claimed','in_flight','unknown') "
                "OR (o.status='accepted' AND NOT EXISTS ("
                "SELECT 1 FROM send_log sl WHERE sl.operation_id=o.operation_id "
                "AND sl.status='sent')))" + operation_exclusion + " LIMIT 1",
                operation_params,
            ).fetchone()
            if operations is not None:
                return "weekly_limit"
        return "allowed"

    def close_legacy_queued_slots_once(self) -> int:
        """Cancel old unclaimed daily work once while preserving outcomes."""
        with self._transaction() as connection:
            done = connection.execute(
                "SELECT 1 FROM weekly_schedule_migrations "
                "WHERE migration_key='close_legacy_daily_slots'"
            ).fetchone()
            if done is not None:
                return 0
            tables = {
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('profile_message_slots','profile_daily_plans')"
                )
            }
            closed = 0
            if tables == {"profile_message_slots", "profile_daily_plans"}:
                cursor = connection.execute(
                    "UPDATE profile_message_slots SET status='cancelled', "
                    "failure_reason='weekly_schedule_cutover', updated_at=? "
                    "WHERE status='queued'",
                    (_utc_now(),),
                )
                closed = int(cursor.rowcount or 0)
            connection.execute(
                "INSERT INTO weekly_schedule_migrations(migration_key, completed_at) "
                "VALUES ('close_legacy_daily_slots', ?)",
                (_utc_now(),),
            )
            return closed

    def slot_for(self, scope: str, profile_id: int, week_start: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM profile_weekly_slots WHERE scope=? AND profile_id=? "
            "AND week_start=?",
            (scope, int(profile_id), week_start),
        ).fetchone()

    def recover_claimed_slots(self, today: str) -> int:
        """Reconcile slots with the durable operation ledger after restart."""
        rows = self.connection.execute(
            "SELECT * FROM profile_weekly_slots WHERE status='claimed'"
        ).fetchall()
        changed = 0
        for row in rows:
            operation = self.connection.execute(
                "SELECT status FROM operations WHERE slot_id=? "
                "ORDER BY created_at DESC LIMIT 1",
                (str(row["slot_id"]),),
            ).fetchone()
            operation_status = str(operation["status"]) if operation else ""
            if operation_status in {"accepted", "unknown"}:
                status = operation_status
            elif str(row["scheduled_date"]) < today:
                status = "expired"
            else:
                status = "queued"
            self.connection.execute(
                "UPDATE profile_weekly_slots SET status=?, updated_at=? WHERE slot_id=?",
                (status, _utc_now(), str(row["slot_id"])),
            )
            changed += 1
        self.connection.commit()
        return changed

    def create_slot(
        self,
        *,
        scope: str,
        profile_id: int,
        week_start: str,
        scheduled_date: str,
        group_id: int,
        message_text: str,
        version_id: str | None,
    ) -> sqlite3.Row:
        slot_id = f"weekly-{uuid.uuid4().hex}"
        now = _utc_now()
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT slot_id FROM profile_weekly_slots "
                "WHERE scope=? AND profile_id=? AND week_start=?",
                (scope, int(profile_id), week_start),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO profile_weekly_slots "
                    "(scope, slot_id, profile_id, week_start, scheduled_date, "
                    "work_group_id, message_text, version_id, status, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)",
                    (
                        scope, slot_id, int(profile_id), week_start, scheduled_date,
                        int(group_id), message_text, version_id, now,
                    ),
                )
                slot_id = slot_id
            else:
                slot_id = str(existing["slot_id"])
        row = self.connection.execute(
            "SELECT * FROM profile_weekly_slots WHERE slot_id=?", (slot_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError("weekly_slot_not_found")
        return row

    def expire_before(self, scope: str, today: str) -> int:
        cursor = self.connection.execute(
            "UPDATE profile_weekly_slots SET status='expired', "
            "failure_reason='scheduled_day_missed', updated_at=? "
            "WHERE scope=? AND status='queued' AND scheduled_date<?",
            (_utc_now(), scope, today),
        )
        self.connection.commit()
        return int(cursor.rowcount or 0)

    def claim_next(
        self,
        scope: str,
        today: str,
        *,
        eligible_assignments: tuple[tuple[int, int], ...],
    ) -> sqlite3.Row | None:
        if not eligible_assignments:
            return None
        clauses = " OR ".join(
            "(profile_id=? AND work_group_id=?)" for _ in eligible_assignments
        )
        params: list[object] = [scope, today]
        for profile_id, group_id in eligible_assignments:
            params.extend((int(profile_id), int(group_id)))
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT slot_id FROM profile_weekly_slots WHERE scope=? "
                "AND scheduled_date=? AND status='queued' AND (" + clauses + ") "
                "ORDER BY profile_id LIMIT 1",
                params,
            ).fetchone()
            if row is None:
                return None
            slot_id = str(row["slot_id"])
            now = _utc_now()
            connection.execute(
                "UPDATE profile_weekly_slots SET status='claimed', claimed_at=?, "
                "updated_at=? WHERE slot_id=? AND status='queued'",
                (now, now, slot_id),
            )
        return self.connection.execute(
            "SELECT * FROM profile_weekly_slots WHERE slot_id=?", (slot_id,)
        ).fetchone()

    def set_slot_status(self, slot_id: str, status: str, reason: str = "") -> None:
        allowed = {"accepted", "failed_unsent", "unknown", "queued"}
        if status not in allowed:
            raise ValueError("unsupported_weekly_slot_status")
        self.connection.execute(
            "UPDATE profile_weekly_slots SET status=?, failure_reason=?, "
            "retry_count=retry_count+?, updated_at=? WHERE slot_id=?",
            (status, str(reason)[:500], 1 if status == "queued" else 0, _utc_now(), slot_id),
        )
        self.connection.commit()

    def slot(self, slot_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM profile_weekly_slots WHERE slot_id=?", (slot_id,)
        ).fetchone()
