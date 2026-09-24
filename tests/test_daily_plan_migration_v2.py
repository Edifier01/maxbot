"""T33 legacy account-day migration guard fixtures."""

from __future__ import annotations

import sqlite3

from app.services.legacy_daily_budget import inspect_legacy_daily_budgets


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE profiles (
            id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            daily_limit INTEGER,
            daily_limit_day TEXT,
            sent_day TEXT,
            messages_sent_today INTEGER DEFAULT 0
        );
        CREATE TABLE send_log (
            id INTEGER PRIMARY KEY,
            profile_id INTEGER,
            status TEXT,
            sent_at TEXT
        );
        """
    )
    return connection


def test_verified_legacy_accepted_count_allows_only_remaining_budget() -> None:
    connection = _connection()
    try:
        connection.execute(
            "INSERT INTO profiles "
            "(id, status, daily_limit, daily_limit_day, sent_day, messages_sent_today) "
            "VALUES (7, 'active', 5, '2026-09-23', '2026-09-23', 2)"
        )
        connection.executemany(
            "INSERT INTO send_log(profile_id, status, sent_at) VALUES (7, 'sent', ?)",
            (("2026-09-23 08:00:00",), ("2026-09-23 09:00:00",)),
        )
        before = dict(connection.execute("SELECT * FROM profiles").fetchone())

        report = inspect_legacy_daily_budgets(connection, "2026-09-23")

        assert [finding.as_dict() for finding in report] == [
            {
                "profile_id": 7,
                "status": "READY",
                "sampled_limit": 5,
                "accepted_today": 2,
                "remaining": 3,
                "reason": "accepted_history_verified",
            }
        ]
        assert dict(connection.execute("SELECT * FROM profiles").fetchone()) == before
    finally:
        connection.close()


def test_ambiguous_legacy_history_requires_review_without_fresh_budget() -> None:
    connection = _connection()
    try:
        connection.execute(
            "INSERT INTO profiles "
            "(id, status, daily_limit, daily_limit_day, sent_day, messages_sent_today) "
            "VALUES (7, 'active', 5, '2026-09-23', '2026-09-23', 2)"
        )
        connection.execute(
            "INSERT INTO send_log(profile_id, status, sent_at) "
            "VALUES (7, 'sent', '2026-09-23 08:00:00')"
        )

        report = inspect_legacy_daily_budgets(connection, "2026-09-23")

        assert report[0].status == "MIGRATION_REVIEW_REQUIRED"
        assert report[0].accepted_today is None
        assert report[0].remaining is None
        assert report[0].reason == "counter_and_accepted_history_disagree"
    finally:
        connection.close()
