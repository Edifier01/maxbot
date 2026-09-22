"""T20 summary queries do not load library text or write business state."""

from __future__ import annotations

import sqlite3

from app.repositories.summary import SummaryRepository


def test_summary_uses_counts_and_scoped_queries_not_full_texts() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE message_set_versions (
            scope TEXT, version_id TEXT, item_count INTEGER, is_current INTEGER,
            checksum TEXT, created_at TEXT
        );
        INSERT INTO message_set_versions VALUES ('tenant:1', 'v1', 100000, 1, 'sha', 'now');
        CREATE TABLE profile_daily_plans (
            scope TEXT, profile_id INTEGER, target INTEGER, role TEXT,
            status TEXT, business_date TEXT
        );
        CREATE TABLE profile_message_slots (scope TEXT, status TEXT);
        CREATE TABLE operations (scope TEXT, status TEXT);
        INSERT INTO profile_daily_plans VALUES ('tenant:1', 7, 5, 'active', 'active', '2026-09-20');
        INSERT INTO profile_message_slots VALUES ('tenant:1', 'accepted');
        """
    )
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    summary = SummaryRepository(connection).read("tenant:1")
    assert summary["library_count"] == 100000
    assert summary["plan_accepted"] == 1
    assert not any("message_set_items" in statement for statement in statements)
    connection.close()
