"""SQLite persistence for revisioned proxy connections and account routes."""

from __future__ import annotations

import sqlite3
from typing import Iterable


class ConnectionRepository:
    """Persist catalog and account assignment state in the current scope DB."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ensure_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS connections (
                id INTEGER PRIMARY KEY,
                version INTEGER NOT NULL DEFAULT 1,
                scheme TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                credential_ref TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                use_count INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS connection_group_pool (
                group_id INTEGER NOT NULL,
                connection_id INTEGER NOT NULL,
                PRIMARY KEY (group_id, connection_id)
            );
            CREATE TABLE IF NOT EXISTS profile_route_assignments (
                profile_id INTEGER PRIMARY KEY,
                automation_group_id INTEGER NOT NULL,
                connection_id INTEGER NOT NULL,
                route_version INTEGER NOT NULL,
                source TEXT NOT NULL,
                assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS profile_automation_groups (
                profile_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                PRIMARY KEY (profile_id, group_id)
            );
            """
        )
        self.conn.commit()

    def add_connection(
        self,
        connection_id: int,
        *,
        scheme: str,
        host: str,
        port: int,
        credential_ref: str,
        enabled: bool = True,
        use_count: int = 0,
    ) -> None:
        if not credential_ref.strip():
            raise ValueError("credential_ref_required")
        self.conn.execute(
            "INSERT OR REPLACE INTO connections "
            "(id, version, scheme, host, port, credential_ref, enabled, use_count, sort_order) "
            "VALUES (?, COALESCE((SELECT version FROM connections WHERE id=?), 1), ?, ?, ?, ?, ?, ?, "
            "COALESCE((SELECT sort_order FROM connections WHERE id=?), ?))",
            (
                int(connection_id),
                int(connection_id),
                scheme,
                host,
                int(port),
                credential_ref,
                1 if enabled else 0,
                int(use_count),
                int(connection_id),
                int(connection_id),
            ),
        )
        self.conn.commit()

    def add_group_connection(self, group_id: int, connection_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO connection_group_pool(group_id, connection_id) VALUES (?, ?)",
            (int(group_id), int(connection_id)),
        )
        self.conn.commit()

    def add_profile_group(self, profile_id: int, group_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO profile_automation_groups(profile_id, group_id) VALUES (?, ?)",
            (int(profile_id), int(group_id)),
        )
        self.conn.commit()

    def assign_route(
        self,
        profile_id: int,
        group_id: int,
        connection_id: int,
        *,
        source: str = "admin_assignment",
    ) -> None:
        row = self.conn.execute(
            "SELECT version FROM connections WHERE id=?", (int(connection_id),)
        ).fetchone()
        if row is None:
            raise ValueError("connection_missing")
        self.conn.execute(
            "INSERT OR REPLACE INTO profile_route_assignments "
            "(profile_id, automation_group_id, connection_id, route_version, source) "
            "VALUES (?, ?, ?, ?, ?)",
            (int(profile_id), int(group_id), int(connection_id), int(row[0]), source),
        )
        self.conn.commit()

    def assignment_for(self, profile_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM profile_route_assignments WHERE profile_id=?",
            (int(profile_id),),
        ).fetchone()

    def set_connection_enabled(self, connection_id: int, enabled: bool) -> None:
        self.conn.execute(
            "UPDATE connections SET enabled=? WHERE id=?",
            (1 if enabled else 0, int(connection_id)),
        )
        self.conn.commit()

    def reorder_connections(self, ids: Iterable[int]) -> None:
        for order, connection_id in enumerate(ids):
            self.conn.execute(
                "UPDATE connections SET sort_order=? WHERE id=?",
                (order, int(connection_id)),
            )
        self.conn.commit()

    def group_connections(self, group_id: int) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT c.* FROM connections c "
                "JOIN connection_group_pool p ON p.connection_id=c.id "
                "WHERE p.group_id=? ORDER BY c.use_count, c.id",
                (int(group_id),),
            ).fetchall()
        )

    def profile_groups(self, profile_id: int) -> list[int]:
        return [
            int(row[0])
            for row in self.conn.execute(
                "SELECT group_id FROM profile_automation_groups WHERE profile_id=? ORDER BY group_id",
                (int(profile_id),),
            ).fetchall()
        ]

    def bump_assignment_use_count(self, connection_id: int) -> None:
        self.conn.execute(
            "UPDATE connections SET use_count=use_count+1 WHERE id=?",
            (int(connection_id),),
        )
        self.conn.commit()
