"""Durable non-secret metadata for authentication attempts."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Mapping


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class AuthAttemptRepository:
    """Persist state metadata only; challenge values never enter this table."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        if self.connection.row_factory is None:
            self.connection.row_factory = sqlite3.Row
        self.ensure_schema(connection)

    @staticmethod
    def ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS auth_attempts (
                attempt_id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                profile_id INTEGER NOT NULL,
                group_id INTEGER,
                mode TEXT NOT NULL,
                revision INTEGER NOT NULL,
                stage TEXT NOT NULL,
                auth_step TEXT NOT NULL,
                stage_deadline_at TEXT,
                attempt_deadline_at TEXT NOT NULL,
                terminal INTEGER NOT NULL DEFAULT 0,
                error_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_auth_attempts_profile
                ON auth_attempts(scope, profile_id, updated_at DESC);
            """
        )

    def save(self, view: Mapping[str, object]) -> None:
        now = _now()
        self.connection.execute(
            """
            INSERT INTO auth_attempts (
                attempt_id, scope, profile_id, group_id, mode, revision, stage,
                auth_step, stage_deadline_at, attempt_deadline_at, terminal,
                error_code, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(attempt_id) DO UPDATE SET
                revision=excluded.revision,
                stage=excluded.stage,
                auth_step=excluded.auth_step,
                stage_deadline_at=excluded.stage_deadline_at,
                attempt_deadline_at=excluded.attempt_deadline_at,
                terminal=excluded.terminal,
                error_code=excluded.error_code,
                updated_at=excluded.updated_at
            """,
            (
                str(view["attempt_id"]),
                str(view["scope"]),
                int(view["profile_id"]),
                view.get("group_id"),
                str(view["mode"]),
                int(view["revision"]),
                str(view["stage"]),
                str(view["auth_step"]),
                view.get("stage_deadline_at"),
                str(view["attempt_deadline_at"]),
                int(bool(view["terminal"])),
                view.get("error_code"),
                now,
                now,
            ),
        )

    def latest(self, scope: str, profile_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM auth_attempts WHERE scope=? AND profile_id=? "
            "ORDER BY updated_at DESC LIMIT 1",
            (str(scope), int(profile_id)),
        ).fetchone()

    def get(
        self, scope: str, profile_id: int, attempt_id: str
    ) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM auth_attempts "
            "WHERE scope=? AND profile_id=? AND attempt_id=?",
            (str(scope), int(profile_id), str(attempt_id)),
        ).fetchone()

    def mark_active_interrupted(self) -> int:
        """Stop persisted attempts from being resumed after a backend restart."""
        cursor = self.connection.execute(
            "UPDATE auth_attempts SET stage='interrupted', "
            "auth_step='error', terminal=1, error_code='ATTEMPT_INTERRUPTED', "
            "stage_deadline_at=NULL, updated_at=? WHERE terminal=0",
            (_now(),),
        )
        return max(0, int(cursor.rowcount or 0))
