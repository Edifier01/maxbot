from __future__ import annotations

import importlib
import sqlite3
from datetime import date

import pytest


def _setup(tmp_path, monkeypatch, *, proxy: str = "socks5://user:pass@proxy.example:1080"):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    monkeypatch.setenv("MAX_DATA", str(tmp_path / "data"))
    import app.config as config

    importlib.reload(config)
    import main

    importlib.reload(main)
    monkeypatch.setattr(main, "ROOT", tmp_path)
    main._refresh_data_paths()
    main.reset_test_runtime()
    main.init_db()
    with main._conn() as connection:
        connection.execute(
            "INSERT INTO profiles(id, phone, status) VALUES (7, '+79990007777', 'active')"
        )
        connection.execute(
            "INSERT INTO groups(id, name, max_chat_id, proxy, is_active) "
            "VALUES (3, 'fixture', '77', ?, 1)",
            (proxy,),
        )
        connection.execute(
            "INSERT INTO group_profiles(group_id, profile_id, is_enabled) VALUES (3, 7, 1)"
        )
        from app.repositories.weekly_schedule import WeeklyScheduleRepository

        WeeklyScheduleRepository(connection).assign_profile(7, 3)
    return main


def test_worker_materializes_and_claims_only_one_weekly_slot(tmp_path, monkeypatch):
    main = _setup(tmp_path, monkeypatch)
    monday = date(2026, 9, 21)
    monkeypatch.setattr(main, "_local_today", lambda: monday)
    from app.repositories.message_sets import MessageSetRepository

    with main._conn() as connection:
        MessageSetRepository(connection).publish("local", ("weekly text", "unused"))
        connection.execute("UPDATE queue_state SET running=1 WHERE id=1")

    from app.campaign_worker import (
        _claim_next_job_sync,
        materialize_weekly_plans,
    )

    assert materialize_weekly_plans() == 1
    job = _claim_next_job_sync()
    assert isinstance(job, dict)
    assert job["weekly_plan"] is True
    assert job["daily_plan_id"] is None
    assert job["slot_id"].startswith("weekly-")
    assert job["text"] in {"weekly text", "unused"}
    assert _claim_next_job_sync() == "WEEKLY_WAIT"


def test_weekly_worker_does_not_create_catchup_slot_after_assigned_day(tmp_path, monkeypatch):
    main = _setup(tmp_path, monkeypatch)
    monday = date(2026, 9, 21)
    monkeypatch.setattr(main, "_local_today", lambda: monday)
    from app.repositories.weekly_schedule import WeeklyScheduleRepository

    repository = WeeklyScheduleRepository(main._conn())
    repository.ensure_schema()
    repository.assign_profile(7, 3)
    main._conn().execute(
        "UPDATE profile_send_schedules SET send_weekday=0 WHERE profile_id=7"
    )
    main._conn().commit()
    from app.repositories.message_sets import MessageSetRepository

    with main._conn() as connection:
        MessageSetRepository(connection).publish("local", ("missed",))

    from app.campaign_worker import materialize_weekly_plans

    assert materialize_weekly_plans() == 1
    monkeypatch.setattr(main, "_local_today", lambda: date(2026, 9, 22))
    assert materialize_weekly_plans() == 0
    assert repository.slot_for("local", 7, "2026-09-21")["status"] == "expired"


def test_proxy_credentials_are_not_in_profile_view(tmp_path, monkeypatch):
    main = _setup(tmp_path, monkeypatch)
    with main._conn() as connection:
        profile = connection.execute("SELECT * FROM profiles WHERE id=7").fetchone()
    public = main._profile_auth_view(profile, group_id=3)
    assert public["send_weekday"] == 0
    assert public["proxy_label"] == "proxy.example:1080"
    assert public["proxy_assigned"] is True
    assert "proxy" not in public
    assert "user" not in repr(public)
    assert "pass" not in repr(public)


def test_send_gateway_enforces_weekday_and_weekly_operation_limit(tmp_path, monkeypatch):
    main = _setup(tmp_path, monkeypatch)
    monday = date(2026, 9, 21)
    monkeypatch.setattr(main, "_local_today", lambda: monday)
    from app.campaign_send import DailyReservationUnavailable, SendTracker, _start_send_operation

    with main._conn() as connection:
        profile = connection.execute("SELECT * FROM profiles WHERE id=7").fetchone()
        group = connection.execute("SELECT * FROM groups WHERE id=3").fetchone()

    first = SendTracker()
    _start_send_operation(tracker=first, profile=profile, group=group, text="weekly")
    assert first.operation_id

    with pytest.raises(DailyReservationUnavailable):
        _start_send_operation(
            tracker=SendTracker(), profile=profile, group=group, text="bypass"
        )

    next_tuesday = date(2026, 9, 29)
    monkeypatch.setattr(main, "_local_today", lambda: next_tuesday)
    with pytest.raises(DailyReservationUnavailable):
        _start_send_operation(
            tracker=SendTracker(), profile=profile, group=group, text="wrong day"
        )
