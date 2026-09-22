"""SQLite persistence for immutable message-library versions."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class MessageSetRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        if self.connection.row_factory is None:
            self.connection.row_factory = sqlite3.Row
        self.ensure_schema(connection)

    @staticmethod
    def ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS message_set_versions (
                scope TEXT NOT NULL,
                version_id TEXT NOT NULL,
                checksum TEXT NOT NULL,
                item_count INTEGER NOT NULL,
                is_current INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                PRIMARY KEY (scope, version_id)
            );
            CREATE TABLE IF NOT EXISTS message_set_items (
                scope TEXT NOT NULL,
                version_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (scope, version_id, item_id),
                UNIQUE (scope, version_id, ordinal),
                FOREIGN KEY (scope, version_id)
                    REFERENCES message_set_versions(scope, version_id)
            );
            CREATE INDEX IF NOT EXISTS idx_message_set_current
                ON message_set_versions(scope, is_current, created_at);
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

    def publish(self, scope: str, items: tuple[str, ...]):
        version_id = f"version-{uuid.uuid4().hex}"
        checksum = hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest()
        now = _now()
        with self._transaction() as connection:
            connection.execute(
                "UPDATE message_set_versions SET is_current=0 WHERE scope=?",
                (scope,),
            )
            connection.execute(
                "INSERT INTO message_set_versions "
                "(scope, version_id, checksum, item_count, is_current, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (scope, version_id, checksum, len(items), now),
            )
            connection.executemany(
                "INSERT INTO message_set_items "
                "(scope, version_id, item_id, ordinal, text) VALUES (?, ?, ?, ?, ?)",
                [
                    (scope, version_id, f"item-{uuid.uuid4().hex}", index, text)
                    for index, text in enumerate(items)
                ],
            )
        return version_id, checksum

    def current(self, scope: str):
        return self.connection.execute(
            "SELECT * FROM message_set_versions WHERE scope=? AND is_current=1 "
            "ORDER BY created_at DESC LIMIT 1",
            (scope,),
        ).fetchone()

    def version(self, scope: str, version_id: str):
        return self.connection.execute(
            "SELECT * FROM message_set_versions WHERE scope=? AND version_id=?",
            (scope, version_id),
        ).fetchone()

    def items(self, scope: str, version_id: str):
        return self.connection.execute(
            "SELECT item_id, text FROM message_set_items "
            "WHERE scope=? AND version_id=? ORDER BY ordinal",
            (scope, version_id),
        ).fetchall()
