"""Bounded, read-only summary queries for status projections."""

from __future__ import annotations

import sqlite3


class SummaryRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def read(self, scope: str) -> dict[str, object]:
        result: dict[str, object] = {
            "scope": scope,
            "library_count": 0,
            "plan_target": 0,
            "plan_accepted": 0,
            "plan_unknown": 0,
            "plan_remaining": 0,
            "plan_waiting": 0,
            "plan_skip": 0,
            "operations_accepted": 0,
            "operations_unknown": 0,
            "operations_failed_unsent": 0,
        }
        tables = {
            str(row["name"])
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "message_set_versions" in tables:
            row = self.connection.execute(
                "SELECT item_count FROM message_set_versions WHERE scope=? AND is_current=1 "
                "ORDER BY created_at DESC LIMIT 1",
                (scope,),
            ).fetchone()
            if row is not None:
                result["library_count"] = int(row["item_count"])
        if "profile_daily_plans" in tables:
            row = self.connection.execute(
                "SELECT COALESCE(SUM(target), 0) AS target, "
                "COALESCE(SUM(CASE WHEN status='waiting_pool' THEN 1 ELSE 0 END), 0) AS waiting, "
                "COALESCE(SUM(CASE WHEN role='skip' THEN 1 ELSE 0 END), 0) AS skip "
                "FROM profile_daily_plans WHERE scope=?",
                (scope,),
            ).fetchone()
            if row is not None:
                result["plan_target"] = int(row["target"])
                result["plan_waiting"] = int(row["waiting"])
                result["plan_skip"] = int(row["skip"])
        if "profile_message_slots" in tables:
            rows = self.connection.execute(
                "SELECT status, COUNT(*) AS n FROM profile_message_slots WHERE scope=? GROUP BY status",
                (scope,),
            ).fetchall()
            counts = {str(row["status"]): int(row["n"]) for row in rows}
            result["plan_accepted"] = counts.get("accepted", 0)
            result["plan_unknown"] = counts.get("unknown", 0)
            result["plan_remaining"] = counts.get("queued", 0) + counts.get("claimed", 0)
        if "operations" in tables:
            rows = self.connection.execute(
                "SELECT status, COUNT(*) AS n FROM operations WHERE scope=? GROUP BY status",
                (scope,),
            ).fetchall()
            counts = {str(row["status"]): int(row["n"]) for row in rows}
            result["operations_accepted"] = counts.get("accepted", 0)
            result["operations_unknown"] = counts.get("unknown", 0)
            result["operations_failed_unsent"] = counts.get("failed_unsent", 0)
        return result
