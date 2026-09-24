from __future__ import annotations

import sqlite3
from datetime import date

import pytest


def _database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE profiles (id INTEGER PRIMARY KEY, phone TEXT, status TEXT);
        CREATE TABLE groups (id INTEGER PRIMARY KEY, proxy TEXT, is_active INTEGER DEFAULT 1);
        CREATE TABLE group_profiles (
            group_id INTEGER, profile_id INTEGER, is_enabled INTEGER DEFAULT 1,
            PRIMARY KEY (group_id, profile_id)
        );
        CREATE TABLE send_log (
            id INTEGER PRIMARY KEY, profile_id INTEGER, status TEXT, sent_at TEXT,
            operation_id TEXT
        );
        CREATE TABLE operations (
            operation_id TEXT PRIMARY KEY, profile_id INTEGER, budget_date TEXT,
            status TEXT
        );
        INSERT INTO groups(id, proxy) VALUES
            (10, 'socks5://one:secret@proxy-a.example:1080\nsocks5://two:secret@proxy-b.example:1080');
        """
    )
    return connection


def test_accounts_get_even_weekdays_and_new_account_uses_least_loaded_proxy():
    from app.repositories.weekly_schedule import WeeklyScheduleRepository

    connection = _database()
    try:
        for profile_id in range(1, 16):
            connection.execute(
                "INSERT INTO profiles(id, phone, status) VALUES (?, ?, 'pending')",
                (profile_id, f"+700000000{profile_id:02d}"),
            )
            connection.execute(
                "INSERT INTO group_profiles(group_id, profile_id) VALUES (10, ?)",
                (profile_id,),
            )
        repository = WeeklyScheduleRepository(connection)
        repository.ensure_schema()
        repository.backfill_assignments()

        weekdays = [
            repository.schedule_for(profile_id)["send_weekday"]
            for profile_id in range(1, 16)
        ]
        assert [weekdays.count(day) for day in range(7)] == [3, 2, 2, 2, 2, 2, 2]

        before = {
            profile_id: repository.assignment_for(profile_id, 10)
            for profile_id in range(1, 16)
        }
        connection.execute(
            "INSERT INTO profiles(id, phone, status) VALUES (16, '+70000000016', 'pending')"
        )
        connection.execute(
            "INSERT INTO group_profiles(group_id, profile_id) VALUES (10, 16)"
        )
        assignment = repository.assign_profile(16, 10)

        assert assignment["send_weekday"] == 1
        assert assignment["proxy_fingerprint"] == before[2]["proxy_fingerprint"]
        assert {
            profile_id: repository.assignment_for(profile_id, 10)
            for profile_id in range(1, 16)
        } == before
    finally:
        connection.close()


def test_proxy_list_edit_preserves_valid_assignments_and_replaces_removed_proxy():
    from app.repositories.weekly_schedule import WeeklyScheduleRepository

    connection = _database()
    try:
        for profile_id in range(1, 5):
            connection.execute(
                "INSERT INTO profiles(id, phone) VALUES (?, ?)",
                (profile_id, f"+711111111{profile_id:02d}"),
            )
            connection.execute(
                "INSERT INTO group_profiles(group_id, profile_id) VALUES (10, ?)",
                (profile_id,),
            )
        repository = WeeklyScheduleRepository(connection)
        repository.ensure_schema()
        repository.backfill_assignments()
        before = {pid: repository.assignment_for(pid, 10) for pid in range(1, 5)}

        repository.update_group_proxy_list(
            10,
            "socks5://two:secret@proxy-b.example:1080\n"
            "socks5://three:secret@proxy-c.example:1080",
        )

        after = {pid: repository.assignment_for(pid, 10) for pid in range(1, 5)}
        assert after[2]["proxy_fingerprint"] == before[2]["proxy_fingerprint"]
        assert after[1]["proxy_fingerprint"] != before[1]["proxy_fingerprint"]
        assert after[3]["proxy_fingerprint"] != before[3]["proxy_fingerprint"]
        assert after[4]["proxy_fingerprint"] == before[4]["proxy_fingerprint"]
        assert repository.proxy_label_for(1, 10) == "proxy-c.example:1080"
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("today", "weekday", "sent_dates", "operation_rows", "expected"),
    [
        (date(2026, 9, 21), 0, (), (), "allowed"),
        (date(2026, 9, 22), 0, (), (), "wrong_day"),
        (date(2026, 9, 21), 0, ("2026-09-20 23:00:00",), (), "weekly_limit"),
        (date(2026, 9, 21), 0, (), (("2026-09-21", "unknown"),), "weekly_limit"),
        (date(2026, 9, 21), 0, (), (("2026-09-20", "failed_unsent"),), "allowed"),
        (date(2026, 9, 28), 0, ("2026-09-20 23:00:00",), (), "allowed"),
    ],
)
def test_weekly_send_guard_uses_monday_to_sunday_window(
    today, weekday, sent_dates, operation_rows, expected
):
    from app.repositories.weekly_schedule import WeeklyScheduleRepository

    connection = _database()
    try:
        connection.execute("INSERT INTO profiles(id, phone) VALUES (1, '+79990000000')")
        connection.execute("INSERT INTO group_profiles(group_id, profile_id) VALUES (10, 1)")
        repository = WeeklyScheduleRepository(connection)
        repository.ensure_schema()
        repository.assign_profile(1, 10)
        connection.execute(
            "UPDATE profile_send_schedules SET send_weekday=? WHERE profile_id=1",
            (weekday,),
        )
        for sent_at in sent_dates:
            connection.execute(
                "INSERT INTO send_log(profile_id, status, sent_at) VALUES (1, 'sent', ?)",
                (sent_at,),
            )
        for budget_date, status in operation_rows:
            connection.execute(
                "INSERT INTO operations(operation_id, profile_id, budget_date, status) "
                "VALUES (?, 1, ?, ?)",
                (f"op-{budget_date}-{status}", budget_date, status),
            )

        assert repository.send_block_reason(1, today) == expected
    finally:
        connection.close()


def test_weekly_slot_is_unique_claimed_once_and_missed_day_expires():
    from app.repositories.weekly_schedule import WeeklyScheduleRepository

    connection = _database()
    try:
        connection.execute("INSERT INTO profiles(id, phone) VALUES (1, '+79990000000')")
        connection.execute("INSERT INTO group_profiles(group_id, profile_id) VALUES (10, 1)")
        repository = WeeklyScheduleRepository(connection)
        repository.ensure_schema()
        first = repository.create_slot(
            scope="local",
            profile_id=1,
            week_start="2026-09-21",
            scheduled_date="2026-09-21",
            group_id=10,
            message_text="one message",
            version_id="v1",
        )
        again = repository.create_slot(
            scope="local",
            profile_id=1,
            week_start="2026-09-21",
            scheduled_date="2026-09-21",
            group_id=10,
            message_text="different retry text",
            version_id="v2",
        )

        assert first["slot_id"] == again["slot_id"]
        assert again["message_text"] == "one message"
        claimed = repository.claim_next(
            "local", "2026-09-21", eligible_assignments=((1, 10),)
        )
        assert claimed["status"] == "claimed"
        assert repository.claim_next(
            "local", "2026-09-21", eligible_assignments=((1, 10),)
        ) is None

        repository.set_slot_status(str(first["slot_id"]), "queued", "proved unsent")
        assert repository.expire_before("local", "2026-09-22") == 1
        assert repository.slot(str(first["slot_id"]))["status"] == "expired"
    finally:
        connection.close()
