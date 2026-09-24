"""Legacy role columns do not influence the weekly schedule."""

from __future__ import annotations

import importlib


def test_legacy_roles_do_not_change_weekday_assignment(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    monkeypatch.setenv("MAX_DATA", str(tmp_path / "data"))
    import app.config as config

    importlib.reload(config)
    import main

    importlib.reload(main)
    monkeypatch.setattr(main, "ROOT", tmp_path)
    main._refresh_data_paths()
    main.init_db()

    with main._conn() as connection:
        group_id = int(connection.execute(
            "INSERT INTO groups (name, proxy) "
            "VALUES ('fixture', 'socks5://proxy.example:1080')"
        ).lastrowid)
        profile_ids = []
        for index, role in enumerate(("active", "quiet", "skip"), 1):
            profile_id = int(connection.execute(
                "INSERT INTO profiles (phone, status) VALUES (?, 'pending')",
                (f"+7999000000{index}",),
            ).lastrowid)
            profile_ids.append(profile_id)
            connection.execute(
                "INSERT INTO group_profiles "
                "(group_id, profile_id, day_role, role_day) "
                "VALUES (?, ?, ?, '2026-09-24')",
                (group_id, profile_id, role),
            )

        from app.repositories.weekly_schedule import WeeklyScheduleRepository

        repository = WeeklyScheduleRepository(connection)
        repository.backfill_assignments()
        schedule = {
            int(row["profile_id"]): int(row["send_weekday"])
            for row in connection.execute(
                "SELECT profile_id, send_weekday FROM profile_send_schedules"
            )
        }
        legacy = [
            tuple(row)
            for row in connection.execute(
                "SELECT profile_id, day_role, role_day FROM group_profiles "
                "ORDER BY profile_id"
            )
        ]

    assert [schedule[profile_id] for profile_id in profile_ids] == [0, 1, 2]
    assert legacy == [
        (profile_ids[0], "active", "2026-09-24"),
        (profile_ids[1], "quiet", "2026-09-24"),
        (profile_ids[2], "skip", "2026-09-24"),
    ]
