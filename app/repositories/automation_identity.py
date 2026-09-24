"""Global registry preventing the same MAX identity from crossing tenants."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3
from typing import Iterator


class AutomationIdentityConflict(RuntimeError):
    """A provider identity is already claimed by another tenant."""

    code = "ACCOUNT_AUTOMATION_CONFLICT"

    def __init__(self) -> None:
        super().__init__(self.code)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class AutomationIdentityRepository:
    """Durable, non-secret ownership claims in the global SQLite scope."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        if self.connection.row_factory is None:
            self.connection.row_factory = sqlite3.Row
        self.ensure_schema(connection)

    @staticmethod
    def ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS automation_identity_claims (
                max_identity TEXT PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                profile_id INTEGER NOT NULL,
                claimed_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (tenant_id, profile_id)
            );
            CREATE INDEX IF NOT EXISTS idx_automation_identity_owner
                ON automation_identity_claims(tenant_id, profile_id);
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

    @staticmethod
    def _identity(value: object) -> str:
        identity = str(value).strip()
        if not identity or len(identity) > 128:
            raise ValueError("provider identity is invalid")
        return identity

    def claim(self, *, tenant_id: int, profile_id: int, max_identity: object) -> None:
        """Claim an identity without revealing an existing tenant on conflict."""
        identity = self._identity(max_identity)
        now = _now()
        with self._transaction() as connection:
            owner = connection.execute(
                "SELECT tenant_id, profile_id FROM automation_identity_claims "
                "WHERE max_identity=?",
                (identity,),
            ).fetchone()
            if owner is not None and (
                int(owner["tenant_id"]) != int(tenant_id)
                or int(owner["profile_id"]) != int(profile_id)
            ):
                raise AutomationIdentityConflict()

            previous = connection.execute(
                "SELECT max_identity FROM automation_identity_claims "
                "WHERE tenant_id=? AND profile_id=?",
                (int(tenant_id), int(profile_id)),
            ).fetchone()
            if previous is not None and str(previous["max_identity"]) != identity:
                connection.execute(
                    "DELETE FROM automation_identity_claims "
                    "WHERE tenant_id=? AND profile_id=?",
                    (int(tenant_id), int(profile_id)),
                )
            connection.execute(
                """
                INSERT INTO automation_identity_claims(
                    max_identity, tenant_id, profile_id, claimed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(max_identity) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (identity, int(tenant_id), int(profile_id), now, now),
            )

    def release(self, *, tenant_id: int, profile_id: int) -> None:
        with self._transaction() as connection:
            connection.execute(
                "DELETE FROM automation_identity_claims WHERE tenant_id=? AND profile_id=?",
                (int(tenant_id), int(profile_id)),
            )
