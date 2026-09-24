"""Pause clears auto_run; start and scheduled start enable daily continuation; retry fails closed."""

from __future__ import annotations

import asyncio
import importlib
import json
import time
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.campaign_runtime import REGISTRY
from app.tenant import get_tenant_id, tenant_scope


@pytest.fixture
def m(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    monkeypatch.setenv("MAX_DATA", str(tmp_path / "data"))
    authorization = tmp_path / "platform-authorization.json"
    now = datetime.now(UTC)
    authorization.write_text(json.dumps({
        "schema_version": 1,
        "reference": "campaign-test-fixture",
        "transport": "authorized_user_session",
        "allowed_actions": ["send"],
        "valid_from": (now - timedelta(days=1)).isoformat(),
        "valid_until": (now + timedelta(days=1)).isoformat(),
    }), encoding="utf-8")
    monkeypatch.setenv("MAX_PLATFORM_AUTHORIZATION_FILE", str(authorization))
    import app.sqlite_backend as sqlite_backend
    import app.config as config
    import main as main_mod

    importlib.reload(config)
    importlib.reload(main_mod)
    sqlite_backend.reset_connections()
    main_mod._refresh_data_paths()
    main_mod.init_db()
    main_mod._settings_cache.clear()
    REGISTRY.reset_test()
    yield main_mod
    sqlite_backend.reset_connections()
    REGISTRY.reset_test()
    main_mod._settings_cache.clear()


def _queue_indices(m) -> tuple[int, int, int]:
    with m._conn() as c:
        row = c.execute(
            "SELECT profile_idx, message_idx, group_idx FROM queue_state WHERE id=1"
        ).fetchone()
    return int(row["profile_idx"]), int(row["message_idx"]), int(row["group_idx"])


def test_pause_clears_auto_run_and_does_not_auto_resume(m, monkeypatch):
    m.set_setting("auto_run", "1")
    with m._conn() as c:
        c.execute(
            "UPDATE queue_state SET profile_idx=3, message_idx=7, group_idx=2 WHERE id=1"
        )
    delay_min = m.get_setting("delay_min_sec")
    delay_max = m.get_setting("delay_max_sec")

    stop_mock = AsyncMock()
    start_mock = AsyncMock()
    monkeypatch.setattr(m, "_stop_worker", stop_mock)
    monkeypatch.setattr(m, "_start_worker", start_mock)
    monkeypatch.setattr(m, "_vault_ready_for_send", lambda: True)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["hello"])
    monkeypatch.setattr(m, "_prepare_auto_resume_pool", lambda: True)
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)

    from app.routes_campaign import campaign_pause

    asyncio.run(campaign_pause())

    assert m.get_setting("auto_run") == "0"
    assert _queue_indices(m) == (3, 7, 2)
    assert m.get_setting("delay_min_sec") == delay_min
    assert m.get_setting("delay_max_sec") == delay_max
    stop_mock.assert_awaited_once()
    assert stop_mock.await_args.kwargs["finish_status"] == "paused"

    resumed = asyncio.run(m._try_auto_resume(log_prefix="Автовозобновление"))
    assert resumed is False
    start_mock.assert_not_awaited()


def test_campaign_start_sets_auto_run(m, monkeypatch):
    assert m.get_setting("auto_run") in ("", "0")

    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["hello"])
    monkeypatch.setattr(m, "_active_groups", lambda: [{"id": 1}])
    monkeypatch.setattr(m, "_has_active_profiles", lambda: True)
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)
    monkeypatch.setattr(m, "_preflight_group_proxies", AsyncMock())
    monkeypatch.setattr(m, "_start_worker", AsyncMock())

    from app.routes_campaign import campaign_start

    asyncio.run(campaign_start())
    assert m.get_setting("auto_run") == "1"


def test_campaign_start_and_worker_share_persisted_generation_fence(m, monkeypatch):
    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["hello"])
    monkeypatch.setattr(m, "_active_groups", lambda: [{"id": 1}])
    monkeypatch.setattr(m, "_has_active_profiles", lambda: True)
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)
    monkeypatch.setattr(m, "_preflight_group_proxies", AsyncMock())
    start_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(m, "_start_worker", start_mock)

    from app.routes_campaign import CampaignCommandCoordinator, campaign_start

    response = asyncio.run(campaign_start(request_id="shared-generation"))
    generation = start_mock.await_args.kwargs["control_generation"]
    assert response["state"] == "running"
    assert generation == response["generation"]

    from app.campaign_worker import _campaign_control_allows_claim

    assert _campaign_control_allows_claim(generation) is True
    CampaignCommandCoordinator(m._conn(), scope="local").stop("legacy-stop")
    assert _campaign_control_allows_claim(generation) is False


def test_auto_resume_logs_only_after_worker_starts(m, monkeypatch):
    m.set_setting("auto_run", "1")
    start_mock = AsyncMock(return_value=True)
    log_mock = MagicMock()
    monkeypatch.setattr(m, "_start_worker", start_mock)
    monkeypatch.setattr(m, "append_log", log_mock)
    monkeypatch.setattr(m, "_vault_ready_for_send", lambda: True)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["hello"])
    monkeypatch.setattr(m, "_prepare_auto_resume_pool", lambda: True)
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)

    assert asyncio.run(m._try_auto_resume()) is True
    start_mock.assert_awaited_once_with(record_campaign=True)
    log_mock.assert_called_once_with("Автовозобновление: рассылка запущена")


def test_auto_resume_accepts_current_immutable_library_without_legacy_pool(m, monkeypatch):
    from app.repositories.message_sets import MessageSetRepository

    MessageSetRepository(m._conn()).publish("local", ("current-library-text",))
    m.set_setting("auto_run", "1")
    start_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(m, "_start_worker", start_mock)
    monkeypatch.setattr(m, "_vault_ready_for_send", lambda: True)
    monkeypatch.setattr(m, "_prepare_auto_resume_pool", lambda: True)
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)

    assert m.load_message_pool() == []
    assert m._has_current_message_library() is True
    assert asyncio.run(m._try_auto_resume()) is True
    start_mock.assert_awaited_once_with(record_campaign=True)


def test_legacy_pool_goal_cannot_activate_old_queue(m):
    from app.campaign_worker import _claim_next_job_sync

    m.set_setting("campaign_goal", "message_pool")
    with m._conn() as connection:
        connection.execute("UPDATE queue_state SET running=1 WHERE id=1")
    assert m._campaign_goal() == "weekly_schedule"
    assert _claim_next_job_sync() == "WEEKLY_DONE"


def test_campaign_preview_is_read_only_and_returns_revision(m):
    from app.repositories.daily_plans import DailyPlanRepository
    from app.repositories.message_sets import MessageSetRepository
    from app.routes_campaign import campaign_preview

    with m._conn() as c:
        c.execute(
            "INSERT INTO profiles (id, phone, status) "
            "VALUES (7, '+79990007777', 'active')"
        )
        c.execute(
            "INSERT INTO groups (id, name, max_chat_id, is_active, proxy) "
            "VALUES (3, 'fixture', '77', 1, 'socks5://proxy.example:1080')"
        )
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, is_enabled) "
            "VALUES (3, 7, 1)"
        )
        from app.repositories.weekly_schedule import WeeklyScheduleRepository

        weekly = WeeklyScheduleRepository(c)
        weekly.assign_profile(7, 3)
        c.execute(
            "UPDATE profile_send_schedules SET send_weekday=? WHERE profile_id=7",
            (m._local_today().weekday(),),
        )
        DailyPlanRepository(c)
        MessageSetRepository(c).publish("local", ("preview-text",))
        before_link = dict(
            c.execute(
                "SELECT * FROM group_profiles WHERE group_id=3 AND profile_id=7"
            ).fetchone()
        )

    response = asyncio.run(campaign_preview())
    repeat_response = asyncio.run(campaign_preview())

    assert response["ok"] is True
    assert response["selection"]["groups"] == [3]
    assert response["selection"]["profiles"] == [7]
    assert len(response["readiness_revision"]) == 64
    assert repeat_response["readiness_revision"] == response["readiness_revision"]
    with m._conn() as c:
        after_link = dict(
            c.execute(
                "SELECT * FROM group_profiles WHERE group_id=3 AND profile_id=7"
            ).fetchone()
        )
        assert c.execute("SELECT COUNT(*) FROM profile_daily_plans").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM daily_cycles").fetchone()[0] == 0
    assert after_link == before_link


def test_campaign_preview_reports_missing_platform_authorization(m, monkeypatch):
    from app.routes_campaign import campaign_preview

    monkeypatch.delenv("MAX_PLATFORM_AUTHORIZATION_FILE")
    response = asyncio.run(campaign_preview())
    assert response["ok"] is False
    assert "max_authorization_record_missing" in response["blockers"]
    assert response["selection"]["external_actions"] == "record_missing"


def test_campaign_preview_reports_window_shortfall_without_mutation(m, monkeypatch):
    from app.campaign_worker import materialize_daily_plans
    from app.repositories.message_sets import MessageSetRepository
    from app.routes_campaign import campaign_preview

    today = m._local_today()
    clock = [datetime.combine(today, datetime.min.time())]
    monkeypatch.setattr(
        m, "_local_now", lambda: clock[0]
    )
    for key, value in (
        ("daily_limit_min", "3"),
        ("daily_limit_max", "3"),
        ("warmup_enabled", "0"),
        ("human_rhythm_enabled", "1"),
        ("delay_min_sec", "60"),
        ("delay_max_sec", "60"),
        ("send_windows_weekday", "00:00-00:01"),
        ("send_windows_weekend", "00:00-00:01"),
    ):
        m.set_setting(key, value)
    with m._conn() as c:
        c.execute(
            "INSERT INTO profiles (id, phone, status) "
            "VALUES (7, '+79990007777', 'active')"
        )
        c.execute(
            "INSERT INTO groups (id, name, max_chat_id, is_active) "
            "VALUES (3, 'fixture', '77', 1)"
        )
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, is_enabled) "
            "VALUES (3, 7, 1)"
        )
        MessageSetRepository(c).publish("local", ("shortfall-text",))

    assert materialize_daily_plans() == 1
    response = asyncio.run(campaign_preview())

    assert response["warnings"] == ["daily_plan_window_shortfall"]
    assert response["selection"]["feasibility"] == {
        "state": "shortfall",
        "planned_slots": 3,
        "minimum_capacity": 1,
        "minimum_delay_sec": 60.0,
        "shortfall": 2,
    }
    with m._conn() as c:
        assert c.execute("SELECT COUNT(*) FROM profile_daily_plans").fetchone()[0] == 1

    clock[0] = datetime.combine(today, datetime.min.time()) + timedelta(minutes=1)
    advanced = asyncio.run(campaign_preview())
    assert advanced["warnings"] == ["daily_plan_window_shortfall"]
    assert advanced["selection"]["feasibility"]["minimum_capacity"] == 0
    assert advanced["selection"]["feasibility"]["shortfall"] == 3


def test_campaign_start_rejects_stale_readiness_revision(m, monkeypatch):
    from app.repositories.message_sets import MessageSetRepository
    from app.routes_campaign import (
        CampaignStartIn,
        _readiness_revision,
        campaign_start,
    )

    with m._conn() as c:
        c.execute(
            "INSERT INTO profiles (id, phone, status) "
            "VALUES (7, '+79990007777', 'active')"
        )
        c.execute(
            "INSERT INTO groups (id, name, max_chat_id, is_active) "
            "VALUES (3, 'fixture', '77', 1)"
        )
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, is_enabled) "
            "VALUES (3, 7, 1)"
        )
        MessageSetRepository(c).publish("local", ("start-text",))

    old_revision = _readiness_revision()
    with m._conn() as c:
        c.execute("UPDATE groups SET is_active=0 WHERE id=3")
    start_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(m, "_start_worker", start_mock)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            campaign_start(
                body=CampaignStartIn(readiness_revision=old_revision),
                request_id="stale-preview",
            )
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "PREVIEW_STALE"
    start_mock.assert_not_awaited()


def test_campaign_preview_and_start_block_ambiguous_legacy_budget(m, monkeypatch):
    from app.repositories.message_sets import MessageSetRepository
    from app.routes_campaign import campaign_preview, campaign_start

    today = m._local_today().isoformat()
    with m._conn() as c:
        c.execute(
            "INSERT INTO profiles "
            "(id, phone, status, daily_limit, daily_limit_day, sent_day, messages_sent_today) "
            "VALUES (7, '+79990007777', 'active', 5, ?, ?, 2)",
            (today, today),
        )
        c.execute(
            "INSERT INTO groups (id, name, max_chat_id, is_active) "
            "VALUES (3, 'fixture', '77', 1)"
        )
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, is_enabled) "
            "VALUES (3, 7, 1)"
        )
        MessageSetRepository(c).publish("local", ("start-text",))
        c.execute(
            "INSERT INTO send_log(profile_id, group_id, status, sent_at) "
            "VALUES (7, 3, 'sent', ?)",
            (f"{today} 08:00:00",),
        )

    preview = asyncio.run(campaign_preview())
    assert preview["ok"] is False
    assert "migration_review_required" in preview["blockers"]
    assert preview["selection"]["migration"] == {
        "state": "review_required",
        "profiles": [7],
    }
    start_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(m, "_start_worker", start_mock)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(campaign_start(request_id="ambiguous-legacy"))
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "MIGRATION_REVIEW_REQUIRED"
    start_mock.assert_not_awaited()


def test_campaign_start_accepts_unchanged_readiness_revision(m, monkeypatch):
    from app.repositories.message_sets import MessageSetRepository
    from app.routes_campaign import CampaignStartIn, _readiness_revision, campaign_start

    with m._conn() as c:
        c.execute(
            "INSERT INTO profiles (id, phone, status) "
            "VALUES (7, '+79990007777', 'active')"
        )
        c.execute(
            "INSERT INTO groups (id, name, max_chat_id, is_active, proxy) "
            "VALUES (3, 'fixture', '77', 1, 'socks5://proxy.example:1080')"
        )
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, is_enabled) "
            "VALUES (3, 7, 1)"
        )
        from app.repositories.weekly_schedule import WeeklyScheduleRepository

        weekly = WeeklyScheduleRepository(c)
        weekly.assign_profile(7, 3)
        c.execute(
            "UPDATE profile_send_schedules SET send_weekday=? WHERE profile_id=7",
            (m._local_today().weekday(),),
        )
        MessageSetRepository(c).publish("local", ("start-text",))

    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m, "_preflight_group_proxies", AsyncMock())
    start_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(m, "_start_worker", start_mock)
    revision = _readiness_revision()

    response = asyncio.run(
        campaign_start(
            body=CampaignStartIn(readiness_revision=revision),
            request_id="fresh-preview",
        )
    )

    assert response["ok"] is True
    assert response["state"] == "running"
    start_mock.assert_awaited_once()
    assert start_mock.await_args.kwargs["preflight"] is False


def test_repeated_start_keeps_one_weekly_slot_per_profile(m, monkeypatch):
    from app.repositories.message_sets import MessageSetRepository
    from app.routes_campaign import campaign_start

    today = m._local_today().isoformat()
    with m._conn() as c:
        for profile_id, limit, group_id in ((7, 5, 3), (8, 7, 4)):
            c.execute(
                "INSERT INTO profiles "
                "(id, phone, status, daily_limit, daily_limit_day, sent_day) "
                "VALUES (?, ?, 'active', ?, ?, ?)",
                (profile_id, f"+7999000{profile_id:04d}", limit, today, today),
            )
            c.execute(
                "INSERT INTO groups (id, name, max_chat_id, is_active, proxy) "
                "VALUES (?, ?, ?, 1, ?)",
                (group_id, f"fixture-{group_id}", str(group_id),
                 f"socks5://proxy-{group_id}.example:1080"),
            )
            c.execute(
                "INSERT INTO group_profiles (group_id, profile_id, is_enabled) "
                "VALUES (?, ?, 1)",
                (group_id, profile_id),
            )
            from app.repositories.weekly_schedule import WeeklyScheduleRepository

            weekly = WeeklyScheduleRepository(c)
            weekly.assign_profile(profile_id, group_id)
            c.execute(
                "UPDATE profile_send_schedules SET send_weekday=? WHERE profile_id=?",
                (m._local_today().weekday(), profile_id),
            )
        library_connection, library_scope = m._message_library_source_storage()
        MessageSetRepository(library_connection).publish(
            library_scope, tuple(f"text-{index}" for index in range(7))
        )

    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m, "_preflight_group_proxies", AsyncMock())
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)
    monkeypatch.setattr(m, "_automation_scope_allows_external_action", lambda *_args: True)
    start_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(m, "_start_worker", start_mock)

    first = asyncio.run(campaign_start(request_id="repeat-start"))
    second = asyncio.run(campaign_start(request_id="repeat-start"))
    with m._conn() as c:
        slots = c.execute(
            "SELECT profile_id, status, work_group_id FROM profile_weekly_slots "
            "WHERE scheduled_date=? ORDER BY profile_id",
            (today,),
        ).fetchall()
        legacy_count = c.execute(
            "SELECT COUNT(*) FROM profile_daily_plans WHERE business_date=?",
            (today,),
        ).fetchone()[0]
    assert [tuple(row) for row in slots] == [(7, "queued", 3), (8, "queued", 4)]
    assert legacy_count == 0

    assert first["state"] == "running"
    assert second["state"] == "running"
    start_mock.assert_awaited_once()
    with m._conn() as c:
        plans = c.execute(
            "SELECT profile_id FROM profile_weekly_slots WHERE scheduled_date=?",
            (today,),
        ).fetchall()
    assert [row["profile_id"] for row in plans] == [7, 8]


def test_auto_run_next_day_materializes_existing_library_without_reimport(m, monkeypatch):
    from app.campaign_worker import materialize_daily_plans
    from app.repositories.message_sets import MessageSetRepository

    today = m._local_today()
    tomorrow = today + timedelta(days=1)
    with m._conn() as c:
        c.execute(
            "INSERT INTO profiles "
            "(id, phone, status, messages_sent_today, sent_day) "
            "VALUES (7, '+79990007777', 'active', 0, ?)",
            (today.isoformat(),),
        )
        c.execute(
            "INSERT INTO groups (id, name, max_chat_id, is_active) "
            "VALUES (3, 'fixture', '77', 1)"
        )
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, is_enabled) "
            "VALUES (3, 7, 1)"
        )
        c.execute(
            "UPDATE profiles SET daily_limit=1, daily_limit_day=? WHERE id=7",
            (today.isoformat(),),
        )
        version_id = MessageSetRepository(c).publish(
            "local", ("reusable-library-text",)
        )[0]

    m.set_setting("daily_limit_min", "1")
    m.set_setting("daily_limit_max", "1")
    m.set_setting("warmup_enabled", "0")
    assert materialize_daily_plans() == 1
    m.set_setting("auto_run", "1")
    monkeypatch.setattr(m, "_local_today", lambda: tomorrow)
    monkeypatch.setattr(m, "_vault_ready_for_send", lambda: True)
    monkeypatch.setattr(m, "_prepare_auto_resume_pool", lambda: True)
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)
    calls: list[dict[str, object]] = []

    async def start_and_materialize(**kwargs):
        calls.append(kwargs)
        assert materialize_daily_plans() == 1
        return True

    monkeypatch.setattr(m, "_start_worker", start_and_materialize)

    assert asyncio.run(m._try_auto_resume(log_prefix="Следующий день")) is True
    assert calls == [{"record_campaign": True}]
    assert m.load_message_pool() == []
    with m._conn() as c:
        plans = c.execute(
            "SELECT business_date, version_id FROM profile_daily_plans "
            "WHERE profile_id=7 ORDER BY business_date"
        ).fetchall()
        texts = c.execute(
            "SELECT p.business_date, s.rendered_text "
            "FROM profile_message_slots s "
            "JOIN profile_daily_plans p ON p.plan_id=s.plan_id "
            "WHERE p.profile_id=7 ORDER BY p.business_date"
        ).fetchall()
    assert [(row["business_date"], row["version_id"]) for row in plans] == [
        (today.isoformat(), version_id),
        (tomorrow.isoformat(), version_id),
    ]
    assert [row["rendered_text"] for row in texts] == [
        "reusable-library-text",
        "reusable-library-text",
    ]


def test_materialization_keeps_production_sampled_bounds_and_auto_run(m):
    from app.campaign_worker import materialize_daily_plans
    from app.repositories.message_sets import MessageSetRepository

    today = m._local_today().isoformat()
    with m._conn() as c:
        c.execute(
            "INSERT INTO profiles (id, phone, status, created_at) "
            "VALUES (7, '+79990007777', 'active', '2026-01-01')"
        )
        c.execute(
            "INSERT INTO groups (id, name, is_active) VALUES (3, 'fixture', 1)"
        )
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, is_enabled) "
            "VALUES (3, 7, 1)"
        )
        MessageSetRepository(c).publish("local", ("sampled-config-text",))

    m.set_setting("daily_limit_min", "5")
    m.set_setting("daily_limit_max", "10")
    m.set_setting("warmup_enabled", "0")
    m.set_setting("auto_run", "1")

    assert materialize_daily_plans() == 1
    with m._conn() as c:
        plan = c.execute(
            "SELECT sampled_limit, target FROM profile_daily_plans "
            "WHERE profile_id=7 AND business_date=?",
            (today,),
        ).fetchone()
    assert 5 <= int(plan["sampled_limit"]) <= 10
    assert 5 <= int(plan["target"]) <= 10
    assert m.get_setting("daily_limit_min") == "5"
    assert m.get_setting("daily_limit_max") == "10"
    assert m.get_setting("auto_run") == "1"


def test_auto_run_zero_does_not_resume_existing_library_on_next_day(m, monkeypatch):
    from app.repositories.message_sets import MessageSetRepository

    today = m._local_today()
    tomorrow = today + timedelta(days=1)
    with m._conn() as connection:
        version_id = MessageSetRepository(connection).publish(
            "local", ("retain-without-auto-run",)
        )[0]

    m.set_setting("auto_run", "0")
    monkeypatch.setattr(m, "_local_today", lambda: tomorrow)
    start_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(m, "_start_worker", start_mock)

    assert asyncio.run(m._try_auto_resume(log_prefix="Следующий день")) is False
    start_mock.assert_not_awaited()
    with m._conn() as connection:
        current = MessageSetRepository(connection).current("local")
        assert connection.execute(
            "SELECT COUNT(*) FROM profile_daily_plans"
        ).fetchone()[0] == 0
    assert current["version_id"] == version_id


@pytest.mark.parametrize("blocker", ["banned", "revoked"])
def test_auto_resume_keeps_library_and_performs_no_action_for_blocked_profile(
    m, monkeypatch, blocker
):
    from app.repositories.message_sets import MessageSetRepository

    today = m._local_today().isoformat()
    with m._conn() as c:
        c.execute(
            "INSERT INTO profiles "
            "(id, phone, status, messages_sent_today, sent_day) "
            "VALUES (7, '+79990007777', ?, 0, ?)",
            ("active" if blocker == "revoked" else "banned", today),
        )
        c.execute(
            "INSERT INTO groups (id, name, max_chat_id, is_active) "
            "VALUES (3, 'fixture', '77', 1)"
        )
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, is_enabled) "
            "VALUES (3, 7, 1)"
        )
        c.execute(
            "UPDATE profiles SET daily_limit=1, daily_limit_day=? WHERE id=7",
            (today,),
        )
        version_id = MessageSetRepository(c).publish("local", ("retain-me",))[0]
        if blocker == "revoked":
            c.execute(
                "CREATE TABLE IF NOT EXISTS profile_automation_scope ("
                "profile_id INTEGER PRIMARY KEY, automation_group_id INTEGER, "
                "consent_state TEXT NOT NULL, revision INTEGER NOT NULL)"
            )
            c.execute(
                "INSERT INTO profile_automation_scope "
                "(profile_id, automation_group_id, consent_state, revision) "
                "VALUES (7, 3, 'revoked', 2)"
            )

    m.set_setting("auto_run", "1")
    monkeypatch.setattr(m, "_vault_ready_for_send", lambda: True)
    start_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(m, "_start_worker", start_mock)

    assert asyncio.run(m._try_auto_resume()) is False
    start_mock.assert_not_awaited()
    with m._conn() as c:
        current = MessageSetRepository(c).current("local")
    assert current["version_id"] == version_id


def test_auto_resume_reuses_running_campaign(m, monkeypatch):
    m.set_setting("auto_run", "1")
    REGISTRY.worker_for(None).current_campaign_id = 7
    start_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(m, "_start_worker", start_mock)
    monkeypatch.setattr(m, "_vault_ready_for_send", lambda: True)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["hello"])
    monkeypatch.setattr(m, "_prepare_auto_resume_pool", lambda: True)
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)

    assert asyncio.run(m._try_auto_resume()) is True
    start_mock.assert_awaited_once_with(record_campaign=False)


def test_auto_resume_does_not_claim_start_when_worker_is_busy(m, monkeypatch):
    m.set_setting("auto_run", "1")
    log_mock = MagicMock()
    monkeypatch.setattr(m, "_start_worker", AsyncMock(return_value=False))
    monkeypatch.setattr(m, "append_log", log_mock)
    monkeypatch.setattr(m, "_vault_ready_for_send", lambda: True)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["hello"])
    monkeypatch.setattr(m, "_prepare_auto_resume_pool", lambda: True)
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)

    assert asyncio.run(m._try_auto_resume()) is False
    log_mock.assert_not_called()


def test_retry_failed_fails_closed_without_state_change(m, monkeypatch):
    m.set_setting("auto_run", "0")
    with m._conn() as c:
        c.execute("INSERT INTO profiles (id, phone) VALUES (1, '+79000000001')")
        c.execute("INSERT INTO groups (id, name) VALUES (1, 'retry-group')")
        c.execute(
            "INSERT INTO send_log (profile_id, group_id, message_idx, status) "
            "VALUES (1, 1, 4, 'failed')"
        )
        c.execute(
            "UPDATE queue_state SET profile_idx=2, message_idx=9, group_idx=3 WHERE id=1"
        )

    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)
    monkeypatch.setattr(m, "_preflight_group_proxies", AsyncMock())
    start_mock = AsyncMock()
    monkeypatch.setattr(m, "_start_worker", start_mock)

    from app.routes_campaign import campaign_retry_failed

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(campaign_retry_failed())

    assert exc_info.value.status_code == 409
    assert m.get_setting("auto_run") == "0"
    assert _queue_indices(m) == (2, 9, 3)
    start_mock.assert_not_awaited()


def test_scheduler_tick_sets_auto_run(m, monkeypatch):
    m.set_setting("auto_run", "0")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with m._conn() as c:
        c.execute(
            "UPDATE campaign_schedule SET enabled=1, start_at=? WHERE id=1",
            (past,),
        )

    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["hello"])
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)
    monkeypatch.setattr(m, "_try_auto_resume", AsyncMock(return_value=False))

    import app.campaign_worker as cw

    start_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(cw, "start_worker", start_mock)
    REGISTRY.reset_test()

    asyncio.run(cw.scheduler_tick())

    assert m.get_setting("auto_run") == "1"
    start_mock.assert_awaited_once()
    assert start_mock.await_args.kwargs["scheduled_for"] == past
    with m._conn() as c:
        row = c.execute("SELECT enabled FROM campaign_schedule WHERE id=1").fetchone()
    assert int(row["enabled"]) == 0


def test_scheduler_does_not_preflight_after_persisted_stop_fence(m, monkeypatch):
    from app.routes_campaign import CampaignCommandCoordinator

    coordinator = CampaignCommandCoordinator(m._conn(), scope="local")
    coordinator.stop("stop-before-scheduled-start")
    m.set_setting("auto_run", "0")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with m._conn() as c:
        c.execute(
            "UPDATE campaign_schedule SET enabled=1, start_at=? WHERE id=1",
            (past,),
        )

    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["hello"])
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)
    preflight = AsyncMock()
    start_worker = AsyncMock(return_value=True)
    monkeypatch.setattr(m, "_preflight_group_proxies", preflight)

    import app.campaign_worker as cw

    monkeypatch.setattr(cw, "start_worker", start_worker)
    monkeypatch.setattr(m, "_try_auto_resume", AsyncMock(return_value=False))

    asyncio.run(cw.scheduler_tick())

    preflight.assert_not_awaited()
    start_worker.assert_not_awaited()
    assert m.get_setting("auto_run") == "0"


def test_scheduler_keeps_due_schedule_when_start_fails(m, monkeypatch):
    m.set_setting("auto_run", "0")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with m._conn() as c:
        c.execute(
            "UPDATE campaign_schedule SET enabled=1, start_at=? WHERE id=1",
            (past,),
        )

    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["hello"])
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)
    monkeypatch.setattr(m, "_preflight_group_proxies", AsyncMock())
    monkeypatch.setattr(m, "_try_auto_resume", AsyncMock(return_value=False))

    import app.campaign_worker as cw

    monkeypatch.setattr(cw, "start_worker", AsyncMock(return_value=False))
    REGISTRY.reset_test()

    asyncio.run(cw.scheduler_tick())

    assert m.get_setting("auto_run") == "0"
    with m._conn() as c:
        row = c.execute("SELECT enabled FROM campaign_schedule WHERE id=1").fetchone()
    assert int(row["enabled"]) == 1


def test_scheduler_logs_errors_in_the_tenant_journal(m, monkeypatch):
    import app.campaign_worker as cw

    monkeypatch.setattr(cw, "scheduler_tenant_ids", lambda: [42])
    monkeypatch.setattr(cw, "scheduler_tick", AsyncMock(side_effect=RuntimeError("boom")))
    seen_tenants = []
    monkeypatch.setattr(cw.main, "append_log", lambda _msg: seen_tenants.append(get_tenant_id()))
    calls = 0

    async def stop_after_one_tick(_seconds):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise StopAsyncIteration

    monkeypatch.setattr(cw.asyncio, "sleep", stop_after_one_tick)

    with pytest.raises(StopAsyncIteration):
        asyncio.run(cw.scheduler_loop())
    assert seen_tenants == [42]


def test_try_auto_resume_skips_expired_subscription(m, monkeypatch):
    import app.db_pg as db_pg

    monkeypatch.setattr(m, "_is_server_mode", lambda: True)
    monkeypatch.setattr(db_pg, "subscription_active", lambda _tid: False)
    start_mock = AsyncMock()
    monkeypatch.setattr(m, "_start_worker", start_mock)
    monkeypatch.setattr(m, "_vault_ready_for_send", lambda: True)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["hello"])
    monkeypatch.setattr(m, "_prepare_auto_resume_pool", lambda: True)
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)

    async def _run():
        with tenant_scope(tenant_id=42, role="user"):
            m.init_db()
            m.set_setting("auto_run", "1")
            resumed = await m._try_auto_resume(log_prefix="Автовозобновление")
            return resumed, m.get_setting("auto_run")

    resumed, auto_run = asyncio.run(_run())
    assert resumed is False
    assert auto_run == "0"
    start_mock.assert_not_awaited()


def test_scheduler_tick_skips_expired_subscription(m, monkeypatch):
    import app.campaign_worker as cw
    import app.db_pg as db_pg

    monkeypatch.setattr(m, "_is_server_mode", lambda: True)
    monkeypatch.setattr(db_pg, "subscription_active", lambda _tid: False)
    start_mock = AsyncMock()
    resume_start = AsyncMock()
    monkeypatch.setattr(cw, "start_worker", start_mock)
    monkeypatch.setattr(m, "_start_worker", resume_start)
    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["hello"])
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)

    async def _run():
        with tenant_scope(tenant_id=42, role="user"):
            m.init_db()
            m.set_setting("auto_run", "1")
            past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            with m._conn() as c:
                c.execute(
                    "UPDATE campaign_schedule SET enabled=1, start_at=? WHERE id=1",
                    (past,),
                )
            await cw.scheduler_tick()
            return m.get_setting("auto_run")

    assert asyncio.run(_run()) == "0"
    start_mock.assert_not_awaited()
    resume_start.assert_not_awaited()


def test_reset_queue_progress_reexported_from_main(m):
    import app.campaign_worker as cw

    assert hasattr(m, "_reset_queue_progress")
    assert m._reset_queue_progress is cw.reset_queue_progress


def test_watchdog_does_not_start_worker_when_auto_run_off(m, monkeypatch):
    import app.campaign_worker as cw

    m.set_setting("auto_run", "0")
    rt = REGISTRY.worker_for(None)
    rt.worker_last_activity = time.monotonic() - m.WORKER_TIMEOUT - 10

    async def hang_forever():
        await asyncio.Event().wait()

    stop_mock = AsyncMock()
    start_mock = AsyncMock()
    monkeypatch.setattr(cw, "stop_worker", stop_mock)
    monkeypatch.setattr(cw, "start_worker", start_mock)

    sleep_calls = 0
    real_sleep = asyncio.sleep

    async def fast_sleep(_sec):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise StopAsyncIteration
        await real_sleep(0)

    monkeypatch.setattr(cw.asyncio, "sleep", fast_sleep)

    loop = asyncio.new_event_loop()
    hang_task = None
    try:
        hang_task = loop.create_task(hang_forever())
        rt.worker_task = hang_task
        with pytest.raises(StopAsyncIteration):
            loop.run_until_complete(cw.watchdog_loop())
    finally:
        if hang_task is not None and not hang_task.done():
            hang_task.cancel()
            loop.run_until_complete(asyncio.gather(hang_task, return_exceptions=True))
        rt.worker_task = None
        loop.close()

    stop_mock.assert_awaited_once()
    assert stop_mock.await_args.kwargs["finish_status"] is None
    start_mock.assert_not_awaited()


def test_watchdog_restart_preserves_campaign_and_counts(m, monkeypatch):
    import app.campaign_worker as cw

    m.set_setting("auto_run", "1")
    rt = REGISTRY.worker_for(None)
    rt.worker_last_activity = time.monotonic() - m.WORKER_TIMEOUT - 10

    async def hang_forever():
        await asyncio.Event().wait()

    stop_mock = AsyncMock()
    start_mock = AsyncMock(return_value=True)
    metric_mock = MagicMock()
    monkeypatch.setattr(cw, "stop_worker", stop_mock)
    monkeypatch.setattr(cw, "start_worker", start_mock)
    monkeypatch.setattr(m, "_metric_inc", metric_mock)

    sleep_calls = 0
    real_sleep = asyncio.sleep

    async def fast_sleep(_sec):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise StopAsyncIteration
        await real_sleep(0)

    monkeypatch.setattr(cw.asyncio, "sleep", fast_sleep)
    loop = asyncio.new_event_loop()
    hang_task = None
    try:
        hang_task = loop.create_task(hang_forever())
        rt.worker_task = hang_task
        with pytest.raises(StopAsyncIteration):
            loop.run_until_complete(cw.watchdog_loop())
    finally:
        if hang_task is not None and not hang_task.done():
            hang_task.cancel()
            loop.run_until_complete(asyncio.gather(hang_task, return_exceptions=True))
        rt.worker_task = None
        loop.close()

    assert stop_mock.await_args.kwargs["finish_status"] is None
    start_mock.assert_awaited_once_with(record_campaign=False)
    metric_mock.assert_called_once_with("worker_restarts_total")


def test_watchdog_survives_failed_restart(m, monkeypatch):
    import app.campaign_worker as cw

    m.set_setting("auto_run", "1")
    rt = REGISTRY.worker_for(None)
    rt.worker_last_activity = time.monotonic() - m.WORKER_TIMEOUT - 10

    async def hang_forever():
        await asyncio.Event().wait()

    async def stop_worker(**_kwargs):
        rt.worker_task = None

    stop_mock = AsyncMock(side_effect=stop_worker)
    start_mock = AsyncMock(side_effect=RuntimeError("proxy down"))
    metric_mock = MagicMock()
    monkeypatch.setattr(cw, "stop_worker", stop_mock)
    monkeypatch.setattr(cw, "start_worker", start_mock)
    monkeypatch.setattr(m, "_metric_inc", metric_mock)

    sleep_calls = 0
    real_sleep = asyncio.sleep

    async def fast_sleep(_sec):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise StopAsyncIteration
        await real_sleep(0)

    monkeypatch.setattr(cw.asyncio, "sleep", fast_sleep)
    loop = asyncio.new_event_loop()
    hang_task = None
    try:
        hang_task = loop.create_task(hang_forever())
        rt.worker_task = hang_task
        with pytest.raises(StopAsyncIteration):
            loop.run_until_complete(cw.watchdog_loop())
    finally:
        if hang_task is not None and not hang_task.done():
            hang_task.cancel()
            loop.run_until_complete(asyncio.gather(hang_task, return_exceptions=True))
        rt.worker_task = None
        loop.close()

    start_mock.assert_awaited_once_with(record_campaign=False)
    metric_mock.assert_not_called()


def test_stop_worker_from_inside_worker_task_does_not_hang(m):
    import app.campaign_worker as cw

    rt = REGISTRY.worker_for(None)
    with m._conn() as c:
        c.execute("UPDATE queue_state SET running=1 WHERE id=1")

    done = asyncio.Event()

    async def fake_worker():
        rt.worker_task = asyncio.current_task()
        await cw.stop_worker(finish_status="stopped", reason="ban from worker")
        done.set()

    async def run_test():
        worker = asyncio.create_task(fake_worker())
        rt.worker_task = worker
        await asyncio.wait_for(done.wait(), timeout=2.0)

    asyncio.run(run_test())

    assert rt.worker_task is None
    with m._conn() as c:
        row = c.execute("SELECT running FROM queue_state WHERE id=1").fetchone()
    assert int(row["running"]) == 0


def test_stop_worker_from_pool_child_does_not_await_supervisor(m):
    import app.campaign_worker as cw

    rt = REGISTRY.worker_for(None)
    with m._conn() as c:
        c.execute("UPDATE queue_state SET running=1 WHERE id=1")

    done = asyncio.Event()

    async def dummy_supervisor():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            for t in list(rt.pool_tasks):
                t.cancel()
            await asyncio.gather(*rt.pool_tasks, return_exceptions=True)
            raise

    async def dummy_sibling():
        await asyncio.Event().wait()

    async def fake_child():
        await cw.stop_worker(finish_status="stopped", reason="ban from pool")
        done.set()

    async def run_test():
        supervisor = asyncio.create_task(dummy_supervisor())
        sibling = asyncio.create_task(dummy_sibling())
        child = asyncio.create_task(fake_child())
        rt.worker_task = supervisor
        rt.pool_tasks = [child, sibling]
        await asyncio.wait_for(done.wait(), timeout=2.0)
        supervisor.cancel()
        sibling.cancel()
        await asyncio.gather(supervisor, sibling, child, return_exceptions=True)

    asyncio.run(run_test())
    with m._conn() as c:
        row = c.execute("SELECT running FROM queue_state WHERE id=1").fetchone()
    assert int(row["running"]) == 0
