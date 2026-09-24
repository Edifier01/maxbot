"""T33 integration: Start materializes durable account-day plans."""

from __future__ import annotations

import importlib
import concurrent.futures
import random
import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _setup_local_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    monkeypatch.setenv("MAX_DATA", str(tmp_path / "data"))
    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.reset_test_runtime()
    m.init_db()
    with m._conn() as connection:
        connection.execute(
            "INSERT INTO profiles (id, phone, status) VALUES (7, '+79990007777', 'active')"
        )
        connection.execute(
            "INSERT INTO groups "
            "(id, name, max_chat_id, destination_verified, is_active, proxy) "
            "VALUES (3, 'fixture', '77', 1, 1, 'socks5://proxy.example:1080')"
        )
        connection.execute(
            "INSERT INTO group_profiles (group_id, profile_id, is_enabled) VALUES (3, 7, 1)"
        )
        from app.repositories.weekly_schedule import WeeklyScheduleRepository

        WeeklyScheduleRepository(connection).assign_profile(7, 3)
        connection.execute(
            "UPDATE profile_send_schedules SET send_weekday=? WHERE profile_id=7",
            (m._local_today().weekday(),),
        )
        profile = connection.execute("SELECT * FROM profiles WHERE id=7").fetchone()
        group = connection.execute("SELECT * FROM groups WHERE id=3").fetchone()
    return m, profile, group


def test_start_materializes_one_plan_from_current_library(tmp_path, monkeypatch) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from app.repositories.message_sets import MessageSetRepository

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=2, daily_limit_day=?, "
            "sent_day=?, messages_sent_today=0 WHERE id=7",
            (today, today),
        )
        MessageSetRepository(connection).publish("local", ("one", "two", "three"))

    from app.campaign_worker import materialize_daily_plans

    assert materialize_daily_plans() == 1
    with m._conn() as connection:
        plan = connection.execute(
            "SELECT profile_id, business_date, target, work_group_id, version_id "
            "FROM profile_daily_plans"
        ).fetchone()
        slots = connection.execute(
            "SELECT rendered_text FROM profile_message_slots ORDER BY ordinal"
        ).fetchall()
    assert tuple(plan) == (7, today, 2, 3, plan["version_id"])
    assert len(slots) == 2
    assert {row["rendered_text"] for row in slots} <= {"one", "two", "three"}


def test_published_v2_waits_for_next_business_day(tmp_path, monkeypatch) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from app.repositories.message_sets import MessageSetRepository

    today = m._local_today()
    tomorrow = today + timedelta(days=1)
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=2, daily_limit_day=?, sent_day=? "
            "WHERE id=7",
            (today.isoformat(), today.isoformat()),
        )
        m.set_setting("daily_limit_min", "2")
        m.set_setting("daily_limit_max", "2")
        m.set_setting("warmup_enabled", "0")
        versions = MessageSetRepository(connection)
        v1 = versions.publish("local", ("v1-one", "v1-two"))[0]

    from app.campaign_worker import materialize_daily_plans

    assert materialize_daily_plans() == 1
    with m._conn() as connection:
        today_plan = connection.execute(
            "SELECT plan_id, version_id FROM profile_daily_plans "
            "WHERE profile_id=7 AND business_date=?",
            (today.isoformat(),),
        ).fetchone()
        today_texts = [
            row["rendered_text"]
            for row in connection.execute(
                "SELECT rendered_text FROM profile_message_slots WHERE plan_id=? "
                "ORDER BY ordinal",
                (today_plan["plan_id"],),
            ).fetchall()
        ]
    # Re-open the application database before publishing the next version;
    # today's plan must remain readable and pinned across an ordinary restart.
    from app import sqlite_backend

    sqlite_backend.reset_connections()
    m.init_db()
    with m._conn() as connection:
        v2 = MessageSetRepository(connection).publish(
            "local", ("v2-one", "v2-two")
        )[0]

    assert today_plan["version_id"] == v1
    assert set(today_texts) == {"v1-one", "v1-two"}
    assert materialize_daily_plans() == 1

    monkeypatch.setattr(m, "_local_today", lambda: tomorrow)
    assert materialize_daily_plans() == 1
    with m._conn() as connection:
        tomorrow_plan = connection.execute(
            "SELECT plan_id, version_id FROM profile_daily_plans "
            "WHERE profile_id=7 AND business_date=?",
            (tomorrow.isoformat(),),
        ).fetchone()
        tomorrow_texts = [
            row["rendered_text"]
            for row in connection.execute(
                "SELECT rendered_text FROM profile_message_slots WHERE plan_id=? "
                "ORDER BY ordinal",
                (tomorrow_plan["plan_id"],),
            ).fetchall()
        ]
    assert tomorrow_plan["version_id"] == v2
    assert set(tomorrow_texts) == {"v2-one", "v2-two"}


def test_proxy_preflight_failure_preserves_plan_for_retry(tmp_path, monkeypatch) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from fastapi import HTTPException

    from app.repositories.message_sets import MessageSetRepository
    from app import routes_campaign

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=5, daily_limit_day=?, "
            "sent_day=?, messages_sent_today=0 WHERE id=7",
            (today, today),
        )
        MessageSetRepository(connection).publish(
            "local", ("one", "two", "three", "four", "five")
        )

    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)
    preflight_calls: list[int] = []

    async def fail_first_preflight() -> None:
        preflight_calls.append(1)
        if len(preflight_calls) == 1:
            raise HTTPException(400, "proxy unavailable")

    monkeypatch.setattr(m, "_preflight_group_proxies", fail_first_preflight)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes_campaign.campaign_start(request_id="proxy-retry-1"))
    assert exc.value.status_code == 400
    assert preflight_calls == [1]

    with m._conn() as connection:
        failed = connection.execute(
            "SELECT slot_id, message_text, status, work_group_id "
            "FROM profile_weekly_slots WHERE profile_id=7 AND scheduled_date=?",
            (today,),
        ).fetchone()
        control = connection.execute(
            "SELECT auto_run, state, stop_requested FROM campaign_control "
            "WHERE scope='local'"
        ).fetchone()
    assert failed is not None
    assert failed["message_text"] in {"one", "two", "three", "four", "five"}
    assert tuple(failed[2:]) == ("queued", 3)
    assert tuple(control) == (0, "stopped", 1)

    monkeypatch.setattr(m, "_preflight_group_proxies", lambda: asyncio.sleep(0))
    response = asyncio.run(routes_campaign.campaign_start(request_id="proxy-retry-2"))
    assert response["state"] == "running"
    with m._conn() as connection:
        retried = connection.execute(
            "SELECT slot_id, message_text FROM profile_weekly_slots "
            "WHERE profile_id=7 AND scheduled_date=?",
            (today,),
        ).fetchone()
    assert tuple(retried) == (failed["slot_id"], failed["message_text"])


def test_stop_start_same_day_keeps_remaining_slots(tmp_path, monkeypatch) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from app.repositories.daily_plans import DailyPlanRepository
    from app.repositories.message_sets import MessageSetRepository
    from app.services.daily_plans import DailyPlanService

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=5, daily_limit_day=?, sent_day=? "
            "WHERE id=7",
            (today, today),
        )
        MessageSetRepository(connection).publish(
            "local", ("one", "two", "three", "four", "five")
        )

    from app.campaign_worker import materialize_daily_plans

    assert materialize_daily_plans() == 1
    service = DailyPlanService(DailyPlanRepository(m._conn()))
    claimed = [
        service.claim_next_slot("local", datetime.now(timezone.utc)) for _ in range(2)
    ]
    for slot in claimed:
        service.mark_slot_accepted(slot.slot_id)
    before = service.materialize_day(
        "local",
        7,
        today,
        sampled_limit=99,
        role="skip",
        quiet_limit=0,
        work_group_id=8,
        library_items=(),
        rng=random.Random(99),
    )

    restarted = DailyPlanService(DailyPlanRepository(m._conn()))
    after = restarted.materialize_day(
        "local",
        7,
        today,
        sampled_limit=1,
        role="quiet",
        quiet_limit=1,
        work_group_id=9,
        library_items=(),
        rng=random.Random(1),
    )
    assert after.plan_id == before.plan_id
    assert after.target == 5
    assert [(slot.item_id, slot.status) for slot in after.slots] == [
        (slot.item_id, slot.status) for slot in before.slots
    ]
    assert sum(slot.status == "queued" for slot in after.slots) == 3


def test_daily_plan_get_100_times_is_read_only_and_does_not_sample(
    tmp_path, monkeypatch
) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from app.repositories.message_sets import MessageSetRepository

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=2, daily_limit_day=?, sent_day=? "
            "WHERE id=7",
            (today, today),
        )
        MessageSetRepository(connection).publish("local", ("one", "two", "three"))

    from app.campaign_worker import materialize_daily_plans
    from app.routes_daily_plans import get_daily_plan

    assert materialize_daily_plans() == 1
    with m._conn() as connection:
        before_plan = dict(
            connection.execute(
                "SELECT * FROM profile_daily_plans WHERE profile_id=7 AND business_date=?",
                (today,),
            ).fetchone()
        )
        before_slots = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM profile_message_slots WHERE plan_id=? ORDER BY ordinal",
                (before_plan["plan_id"],),
            ).fetchall()
        ]

    import app.services.daily_plans as daily_plans

    class ForbiddenRandom:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("GET must not create an RNG")

    monkeypatch.setattr(daily_plans.random, "Random", ForbiddenRandom)
    responses = [
        asyncio.run(get_daily_plan(7, business_date=today)) for _ in range(100)
    ]
    assert all(response["plan"]["plan_id"] == before_plan["plan_id"] for response in responses)
    assert all(len(response["slots"]) == len(before_slots) for response in responses)

    with m._conn() as connection:
        after_plan = dict(
            connection.execute(
                "SELECT * FROM profile_daily_plans WHERE profile_id=7 AND business_date=?",
                (today,),
            ).fetchone()
        )
        after_slots = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM profile_message_slots WHERE plan_id=? ORDER BY ordinal",
                (before_plan["plan_id"],),
            ).fetchall()
        ]
    assert after_plan == before_plan
    assert after_slots == before_slots


def test_yesterday_counters_require_explicit_plan_and_survive_reset_restart(
    tmp_path, monkeypatch
) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from fastapi import HTTPException
    from app import sqlite_backend
    from app.repositories.message_sets import MessageSetRepository
    from app.routes_daily_plans import get_daily_plan

    today = m._local_today()
    yesterday = today - timedelta(days=1)
    m.set_setting("daily_limit_min", "2")
    m.set_setting("daily_limit_max", "2")
    m.set_setting("warmup_enabled", "0")
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=5, daily_limit_day=?, "
            "sent_day=?, messages_sent_today=4 WHERE id=7",
            (yesterday.isoformat(), yesterday.isoformat()),
        )
        MessageSetRepository(connection).publish("local", ("one", "two", "three"))

    with pytest.raises(HTTPException) as missing:
        asyncio.run(get_daily_plan(7, business_date=today.isoformat()))
    assert missing.value.status_code == 404

    from app.campaign_worker import materialize_daily_plans

    assert materialize_daily_plans() == 1
    with m._conn() as connection:
        before_plan = dict(
            connection.execute(
                "SELECT * FROM profile_daily_plans WHERE profile_id=7 AND business_date=?",
                (today.isoformat(),),
            ).fetchone()
        )
        before_slots = [
            dict(row)
            for row in connection.execute(
                "SELECT slot_id, ordinal, item_id, pass_index, version_id, "
                "rendered_text, status, failure_reason, retry_count "
                "FROM profile_message_slots WHERE plan_id=? ORDER BY ordinal",
                (before_plan["plan_id"],),
            ).fetchall()
        ]
        m._reset_daily_counts(connection)

    after_reset = asyncio.run(get_daily_plan(7, business_date=today.isoformat()))
    assert after_reset["plan"] == before_plan
    assert after_reset["slots"] == before_slots

    sqlite_backend.reset_connections()
    m.init_db()
    after_restart = asyncio.run(get_daily_plan(7, business_date=today.isoformat()))
    assert after_restart["plan"] == before_plan
    assert after_restart["slots"] == before_slots


def test_new_business_date_expires_queued_slots_without_replaying_unknown(
    tmp_path, monkeypatch
) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from app.repositories.daily_plans import DailyPlanRepository
    from app.repositories.message_sets import MessageSetRepository
    from app.services.daily_plans import DailyPlanService, LibraryItem

    today = m._local_today()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    with m._conn() as connection:
        version_id = MessageSetRepository(connection).publish(
            "local", ("old-one", "old-two", "old-three")
        )[0]
        items = tuple(
            LibraryItem(str(row["item_id"]), str(row["text"]), version_id)
            for row in MessageSetRepository(connection).items("local", version_id)
        )

    service = DailyPlanService(DailyPlanRepository(m._conn()))
    old_plan = service.materialize_day(
        "local",
        7,
        yesterday.isoformat(),
        sampled_limit=3,
        role="active",
        quiet_limit=1,
        work_group_id=3,
        library_items=items,
    )
    unknown = service.claim_next_slot(
        "local", datetime.combine(yesterday, datetime.min.time(), tzinfo=timezone.utc)
    )
    service.mark_slot_unknown(unknown.slot_id, "timeout after transmit")

    monkeypatch.setattr(m, "_local_today", lambda: tomorrow)
    from app.campaign_worker import materialize_daily_plans

    assert materialize_daily_plans() == 1
    with m._conn() as connection:
        old_statuses = [
            row["status"]
            for row in connection.execute(
                "SELECT status FROM profile_message_slots WHERE plan_id=? ORDER BY ordinal",
                (old_plan.plan_id,),
            ).fetchall()
        ]
        new_plan = connection.execute(
            "SELECT business_date FROM profile_daily_plans "
            "WHERE profile_id=7 AND business_date=?",
            (tomorrow.isoformat(),),
        ).fetchone()
    assert old_statuses == ["unknown", "expired", "expired"]
    assert new_plan["business_date"] == tomorrow.isoformat()


def test_legacy_verified_accepted_sends_reduce_first_daily_plan(tmp_path, monkeypatch) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from app.repositories.message_sets import MessageSetRepository

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=5, daily_limit_day=?, sent_day=?, "
            "messages_sent_today=2 WHERE id=7",
            (today, today),
        )
        MessageSetRepository(connection).publish(
            "local", ("one", "two", "three", "four", "five")
        )
        connection.executemany(
            "INSERT INTO send_log(profile_id, group_id, status, sent_at) "
            "VALUES (7, 3, 'sent', ?)",
            ((f"{today} 08:00:00",), (f"{today} 09:00:00",)),
        )

    from app.campaign_worker import materialize_daily_plans

    assert materialize_daily_plans() == 1
    with m._conn() as connection:
        plan = connection.execute(
            "SELECT target FROM profile_daily_plans WHERE profile_id=7 AND business_date=?",
            (today,),
        ).fetchone()
        slots = connection.execute(
            "SELECT COUNT(*) FROM profile_message_slots"
        ).fetchone()[0]
    assert plan["target"] == 3
    assert slots == 3


def test_legacy_ambiguous_history_blocks_fresh_daily_plan(tmp_path, monkeypatch) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from app.repositories.message_sets import MessageSetRepository

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=5, daily_limit_day=?, sent_day=?, "
            "messages_sent_today=2 WHERE id=7",
            (today, today),
        )
        MessageSetRepository(connection).publish("local", ("one", "two", "three"))
        connection.execute(
            "INSERT INTO send_log(profile_id, group_id, status, sent_at) "
            "VALUES (7, 3, 'sent', ?)",
            (f"{today} 08:00:00",),
        )

    from app.campaign_worker import MigrationReviewRequired, materialize_daily_plans

    with pytest.raises(MigrationReviewRequired) as caught:
        materialize_daily_plans()
    assert caught.value.findings[0]["reason"] == "counter_and_accepted_history_disagree"
    with m._conn() as connection:
        assert connection.execute("SELECT COUNT(*) FROM profile_daily_plans").fetchone()[0] == 0


def test_concurrent_materialize_creates_one_plan_and_slot_set(tmp_path) -> None:
    db_path = tmp_path / "daily-plan-race.db"
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    from app.repositories.daily_plans import DailyPlanRepository

    DailyPlanRepository(connection)
    connection.close()

    from app.services.daily_plans import DailyPlanService, LibraryItem

    items = tuple(LibraryItem(f"item-{i}", f"text-{i}", "version-v1") for i in range(5))

    def materialize(seed: int):
        worker_connection = sqlite3.connect(db_path, timeout=10)
        worker_connection.row_factory = sqlite3.Row
        try:
            return DailyPlanService(DailyPlanRepository(worker_connection)).materialize_day(
                "local",
                7,
                "2026-09-20",
                sampled_limit=5,
                role="active",
                quiet_limit=1,
                work_group_id=3,
                library_items=items,
                rng=random.Random(seed),
            )
        finally:
            worker_connection.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(materialize, (1, 2))

    assert first.plan_id == second.plan_id
    final = sqlite3.connect(db_path)
    try:
        assert final.execute("SELECT COUNT(*) FROM profile_daily_plans").fetchone()[0] == 1
        assert final.execute("SELECT COUNT(*) FROM profile_message_slots").fetchone()[0] == 5
    finally:
        final.close()


def test_server_worker_reads_global_library_but_materializes_tenant_plan(
    tmp_path, monkeypatch
) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from app.repositories.message_sets import MessageSetRepository
    from app.tenant import tenant_scope

    global_connection = sqlite3.connect(":memory:")
    global_connection.row_factory = sqlite3.Row
    global_connection.executescript(
        """
        CREATE TABLE message_pool (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            order_index INTEGER NOT NULL,
            loaded_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE queue_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            profile_idx INTEGER DEFAULT 0,
            message_idx INTEGER DEFAULT 0,
            group_idx INTEGER DEFAULT 0,
            message_bag TEXT DEFAULT '[]'
        );
        INSERT INTO queue_state (id) VALUES (1);
        """
    )

    tenant_connection = m._conn()
    monkeypatch.setattr(m, "_is_server_mode", lambda: True)
    monkeypatch.setattr(m, "_conn", lambda: tenant_connection)
    monkeypatch.setattr(m, "_global_conn", lambda: global_connection)

    with tenant_scope(tenant_id=7, role="user"):
        assert m._message_library_storage()[1] == "tenant:7"
        assert m._message_library_storage()[0] is tenant_connection
        assert m._global_conn() is global_connection

        assert m.save_messages_file(b"global text\n") == 1
        from app.routes_campaign import _library_available

        assert _library_available([]) is True
        version_id = MessageSetRepository(global_connection).current("global")[
            "version_id"
        ]

        from app.campaign_worker import materialize_daily_plans

        assert materialize_daily_plans() == 1

    with tenant_connection:
        plan = tenant_connection.execute(
            "SELECT scope, version_id FROM profile_daily_plans"
        ).fetchone()
    assert plan["scope"] == "tenant:7"
    assert plan["version_id"] == version_id


def test_start_worker_materializes_weekly_plan_before_recovery_and_preflight(tmp_path, monkeypatch) -> None:
    _m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    import app.campaign_worker as campaign_worker

    calls: list[str] = []
    monkeypatch.setattr(
        campaign_worker,
        "materialize_weekly_plans",
        lambda: calls.append("materialize") or 1,
    )
    monkeypatch.setattr(
        campaign_worker,
        "recover_inflight_operations",
        lambda: calls.append("recover") or [],
    )
    monkeypatch.setattr(
        campaign_worker.main,
        "_preflight_group_proxies",
        lambda: calls.append("preflight") or asyncio.sleep(0),
    )
    monkeypatch.setattr(campaign_worker, "pool_supervisor", lambda: asyncio.sleep(0))
    monkeypatch.setattr(campaign_worker.main, "append_log", lambda _message: None)

    async def _run() -> None:
        assert await campaign_worker.start_worker(record_campaign=False) is True
        runtime = campaign_worker.REGISTRY.worker_for(None)
        if runtime.worker_task is not None:
            await runtime.worker_task

    asyncio.run(_run())

    assert calls == ["materialize", "recover", "preflight"]


def test_retired_daily_slot_cannot_bypass_weekly_send_guard(
    tmp_path, monkeypatch
) -> None:
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.repositories.daily_plans import DailyPlanRepository
    from app.repositories.message_sets import MessageSetRepository
    from app.services.daily_plans import DailyPlanService

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=1, daily_limit_day=?, sent_day=? WHERE id=7",
            (today, today),
        )
        MessageSetRepository(connection).publish("local", ("slot text",))

    from app.campaign_worker import materialize_daily_plans

    assert materialize_daily_plans() == 1
    with m._conn() as connection:
        claimed = DailyPlanService(DailyPlanRepository(connection)).claim_next_slot(
            "local", datetime.now(timezone.utc)
        )
        assert hasattr(claimed, "slot_id")

    class Gateway:
        async def check_destination(self, *, chat_id: int):
            return None

        async def send_message(self, *, chat_id: int, text: str):
            return SimpleNamespace(message_id="provider-slot-1")

    gateway = Gateway()
    monkeypatch.setattr(m, "MAX_RETRY", 1)
    monkeypatch.setattr(m, "RETRY_DELAYS", [0])
    monkeypatch.setattr(m, "_prepare_outgoing_text", lambda text, *_a, **_k: text)
    monkeypatch.setattr(m, "_max_gateway", lambda _client: gateway)
    monkeypatch.setattr(m, "_touch_worker_activity", lambda: None)
    monkeypatch.setattr(m, "_on_success", lambda _profile_id: None)
    monkeypatch.setattr(m, "_note_human_burst", lambda _profile_id: None)
    monkeypatch.setattr(m, "_metric_inc", lambda _key: None)
    monkeypatch.setattr(m, "append_log", lambda _message: None)

    async def with_fake_client(_profile_id, _phone, callback, **_kwargs):
        return await callback(object())

    monkeypatch.setattr(m, "_with_client", with_fake_client)

    from app.campaign_send import send_with_retry

    assert asyncio.run(
        send_with_retry(
            profile,
            group,
            claimed.rendered_text,
            0,
            0,
            0,
            0,
            daily_plan_id=claimed.plan_id,
            slot_id=claimed.slot_id,
        )
    ) is False

    with m._conn() as connection:
        assert connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM send_log").fetchone()[0] == 0


def test_worker_claims_pinned_weekly_slot_before_legacy_message_pool(
    tmp_path, monkeypatch
) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from app.repositories.message_sets import MessageSetRepository

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=1, daily_limit_day=?, sent_day=? WHERE id=7",
            (today, today),
        )
        connection.execute("UPDATE queue_state SET running=1 WHERE id=1")
        MessageSetRepository(connection).publish("local", ("pinned slot",))

    from app.campaign_worker import _claim_next_job_sync, materialize_weekly_plans

    assert materialize_weekly_plans() == 1
    job = _claim_next_job_sync()

    assert isinstance(job, dict)
    assert job["text"] == "pinned slot"
    assert job["daily_plan_id"] is None
    assert job["weekly_plan"] is True
    assert job["slot_id"]
    assert job["profile"]["id"] == 7
    assert job["group"]["id"] == 3


def test_worker_finalizes_daily_slot_without_releasing_unknown_budget(
    tmp_path, monkeypatch
) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_worker import (
        _claim_daily_job_sync,
        _finalize_daily_job,
        materialize_daily_plans,
    )
    from app.campaign_send import SendTracker
    from app.repositories.message_sets import MessageSetRepository

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=1, daily_limit_day=?, sent_day=? WHERE id=7",
            (today, today),
        )
        MessageSetRepository(connection).publish("local", ("slot text",))

    assert materialize_daily_plans() == 1
    job = _claim_daily_job_sync()
    assert isinstance(job, dict)
    unknown = SendTracker()
    unknown.mark_unknown("timeout after transmit")
    _finalize_daily_job(job, False, unknown)

    with m._conn() as connection:
        slot = connection.execute(
            "SELECT status, failure_reason FROM profile_message_slots WHERE slot_id=?",
            (job["slot_id"],),
        ).fetchone()
    assert tuple(slot) == ("unknown", "timeout after transmit")


def test_worker_requeues_only_proven_pre_send_daily_slot(
    tmp_path, monkeypatch
) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_worker import (
        _claim_daily_job_sync,
        _finalize_daily_job,
        materialize_daily_plans,
    )
    from app.campaign_send import SendTracker
    from app.repositories.message_sets import MessageSetRepository

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=1, daily_limit_day=?, sent_day=? WHERE id=7",
            (today, today),
        )
        MessageSetRepository(connection).publish("local", ("slot text",))

    assert materialize_daily_plans() == 1
    job = _claim_daily_job_sync()
    assert isinstance(job, dict)
    failed = SendTracker()
    failed.mark_failed_unsent("destination check failed before send")
    _finalize_daily_job(job, False, failed)

    with m._conn() as connection:
        slot = connection.execute(
            "SELECT status, failure_reason FROM profile_message_slots WHERE slot_id=?",
            (job["slot_id"],),
        ).fetchone()
    assert tuple(slot) == ("queued", "")


def test_a43_message_import_preview_publish_and_retry_keep_frozen_text(
    tmp_path, monkeypatch
) -> None:
    """The complete A43 content path stays deterministic and local-only."""
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import SendTracker, send_with_retry
    from app.campaign_worker import (
        _claim_weekly_job_sync,
        _finalize_weekly_job,
        materialize_weekly_plans,
    )
    from app.repositories.message_sets import MessageSetRepository
    from app.routes_message_sets import MessagePreviewIn, preview_message_set

    raw = (
        "\ufeff# fixture comment\n"
        '"a,b" — Привет 🚀\n'
        '{"value":"a|b"}\n'
        '"a,b" — Привет 🚀\n'
    )
    preview = asyncio.run(preview_message_set(MessagePreviewIn(raw=raw)))
    expected_items = [
        '"a,b" — Привет 🚀',
        '{"value":"a|b"}',
        '"a,b" — Привет 🚀',
    ]
    assert preview["valid"] is True
    assert preview["items"] == expected_items
    assert preview["warnings"] == ["duplicate_texts_are_allowed"]

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=3, daily_limit_day=?, "
            "sent_day=?, messages_sent_today=0 WHERE id=7",
            (today, today),
        )
    m.set_setting("message_pick_mode", "round_robin")
    assert m.save_messages_file(raw.encode("utf-8")) == len(expected_items)

    with m._conn() as connection:
        repository = MessageSetRepository(connection)
        published = repository.current("local")
        assert published is not None
        assert [
            row["text"] for row in repository.items("local", published["version_id"])
        ] == expected_items

    assert materialize_weekly_plans() == 1
    job = _claim_weekly_job_sync()
    assert isinstance(job, dict)
    frozen_text = str(job["text"])
    assert frozen_text == expected_items[0]

    failed = SendTracker()
    failed.mark_failed_unsent("destination check failed before send")
    _finalize_weekly_job(job, False, failed)

    # Publishing a new current version must not mutate the already materialized slot.
    with m._conn() as connection:
        MessageSetRepository(connection).publish("local", ("replacement version",))

    retry_job = _claim_weekly_job_sync()
    assert isinstance(retry_job, dict)
    assert retry_job["slot_id"] == job["slot_id"]
    assert retry_job["text"] == frozen_text

    class FakeGateway:
        def __init__(self) -> None:
            self.check_calls = 0
            self.sent_texts: list[str] = []

        async def check_destination(self, *, chat_id: int) -> None:
            self.check_calls += 1
            if self.check_calls == 1:
                raise RuntimeError("fixture proxy unavailable before send")

        async def send_message(self, *, chat_id: int, text: str):
            self.sent_texts.append(text)
            return SimpleNamespace(message_id="fixture-a43-message")

    gateway = FakeGateway()
    monkeypatch.setattr(m, "MAX_RETRY", 2)
    monkeypatch.setattr(m, "RETRY_DELAYS", [0, 0])
    monkeypatch.setattr(m, "_prepare_outgoing_text", lambda text, *_a, **_k: text)
    monkeypatch.setattr(m, "_max_gateway", lambda _client: gateway)
    monkeypatch.setattr(m, "_touch_worker_activity", lambda: None)
    monkeypatch.setattr(m, "_on_success", lambda _profile_id: None)
    monkeypatch.setattr(m, "_note_human_burst", lambda _profile_id: None)
    monkeypatch.setattr(m, "_metric_inc", lambda _key: None)
    monkeypatch.setattr(m, "append_log", lambda _message: None)

    async def with_fake_client(_profile_id, _phone, callback, **_kwargs):
        return await callback(object())

    monkeypatch.setattr(m, "_with_client", with_fake_client)
    tracker = SendTracker()
    assert asyncio.run(
        send_with_retry(
            retry_job["profile"],
            retry_job["group"],
            retry_job["text"],
            retry_job["mi"],
            retry_job["pi"],
            retry_job["gi_next"],
            retry_job["mi_next"],
            advance_queue=False,
            tracker=tracker,
            daily_plan_id=None,
            slot_id=retry_job["slot_id"],
        )
    ) is True
    _finalize_weekly_job(retry_job, True, tracker)

    assert gateway.check_calls == 2
    assert gateway.sent_texts == [frozen_text]
    with m._conn() as connection:
        slot = connection.execute(
            "SELECT status, message_text FROM profile_weekly_slots WHERE slot_id=?",
            (retry_job["slot_id"],),
        ).fetchone()
        operation = connection.execute(
            "SELECT status, text FROM operations WHERE slot_id=?",
            (retry_job["slot_id"],),
        ).fetchone()
    assert tuple(slot) == ("accepted", frozen_text)
    assert tuple(operation) == ("accepted", frozen_text)


def test_manual_test_uses_the_claimed_weekly_slot_when_library_is_published(
    tmp_path, monkeypatch
) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from app.repositories.message_sets import MessageSetRepository

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=1, daily_limit_day=?, sent_day=? WHERE id=7",
            (today, today),
        )
    m.save_messages_file("legacy text\n".encode())
    with m._conn() as connection:
        MessageSetRepository(connection).publish("local", ("pinned manual text",))

    from app.campaign_worker import materialize_weekly_plans

    assert materialize_weekly_plans() == 1
    from app import routes_campaign

    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m.RUNTIME, "worker_busy", lambda: False)
    monkeypatch.setattr(m, "_is_circuit_open", lambda _profile_id: False)
    monkeypatch.setattr(m, "_can_send_in_group", lambda _profile, _group_id: True)

    async def fake_preflight():
        return None

    monkeypatch.setattr(
        routes_campaign.m, "_preflight_group_proxies", fake_preflight, raising=False
    )

    async def fake_send(*args, **kwargs):
        return True

    send = AsyncMock(side_effect=fake_send)
    monkeypatch.setattr(routes_campaign.m, "_send_with_retry", send, raising=False)

    result = asyncio.run(routes_campaign.campaign_test())

    assert result["ok"] is True
    assert send.await_args.args[2] == "pinned manual text"
    assert send.await_args.kwargs["daily_plan_id"] is None
    assert send.await_args.kwargs["slot_id"].startswith("weekly-")
    assert send.await_args.kwargs["slot_id"]


def test_manual_test_cannot_send_after_weekly_slot_is_used(
    tmp_path, monkeypatch
) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from fastapi import HTTPException
    from app.repositories.message_sets import MessageSetRepository
    from app.routes_campaign import campaign_test

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=5, daily_limit_day=?, sent_day=? "
            "WHERE id=7",
            (today, today),
        )
        MessageSetRepository(connection).publish(
            "local", ("one", "two", "three", "four", "five")
        )
        connection.execute(
            "INSERT INTO send_log(profile_id, group_id, status, sent_at) "
            "VALUES (7, 3, 'sent', ?)",
            (datetime.now(timezone.utc).isoformat(),),
        )

    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m.RUNTIME, "worker_busy", lambda: False)
    preflight = AsyncMock()
    monkeypatch.setattr(m, "_preflight_group_proxies", preflight)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(campaign_test())

    assert caught.value.status_code == 409
    assert "неделе" in str(caught.value.detail).lower()
    preflight.assert_not_awaited()
    preflight.assert_not_awaited()


def test_concurrent_manual_tests_reserve_one_weekly_slot(
    tmp_path, monkeypatch
) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from fastapi import HTTPException
    from app.repositories.message_sets import MessageSetRepository
    from app.routes_campaign import campaign_test

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=1, daily_limit_day=?, sent_day=? "
            "WHERE id=7",
            (today, today),
        )
        MessageSetRepository(connection).publish("local", ("one remaining",))

    from app.campaign_worker import materialize_weekly_plans

    assert materialize_weekly_plans() == 1
    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m.RUNTIME, "worker_busy", lambda: False)

    async def preflight() -> None:
        await asyncio.sleep(0)

    monkeypatch.setattr(m, "_preflight_group_proxies", preflight)
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(m, "_send_with_retry", send)

    async def run_both():
        return await asyncio.gather(
            campaign_test(), campaign_test(), return_exceptions=True
        )

    results = asyncio.run(run_both())
    successes = [result for result in results if isinstance(result, dict)]
    conflicts = [result for result in results if isinstance(result, HTTPException)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert conflicts[0].status_code == 409
    assert send.await_count == 1
    with m._conn() as connection:
        assert connection.execute(
            "SELECT status FROM profile_weekly_slots"
        ).fetchone()[0] == "accepted"
