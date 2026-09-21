"""T33 integration: Start materializes durable account-day plans."""

from __future__ import annotations

import importlib
import sqlite3
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock


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
            "INSERT INTO groups (id, name, max_chat_id, is_active) VALUES (3, 'fixture', '77', 1)"
        )
        connection.execute(
            "INSERT INTO group_profiles (group_id, profile_id, is_enabled) VALUES (3, 7, 1)"
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


def test_start_worker_materializes_before_recovery_and_preflight(tmp_path, monkeypatch) -> None:
    _m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    import app.campaign_worker as campaign_worker

    calls: list[str] = []
    monkeypatch.setattr(
        campaign_worker,
        "materialize_daily_plans",
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


def test_daily_slot_identity_is_carried_into_operation_and_send_log(
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
            "local", m._local_now().replace(tzinfo=None)
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
    ) is True

    with m._conn() as connection:
        operation = connection.execute(
            "SELECT daily_plan_id, slot_id, status FROM operations"
        ).fetchone()
        send_log = connection.execute(
            "SELECT daily_plan_id, slot_id, status FROM send_log"
        ).fetchone()
    assert tuple(operation) == (claimed.plan_id, claimed.slot_id, "accepted")
    assert tuple(send_log) == (claimed.plan_id, claimed.slot_id, "sent")


def test_worker_claims_pinned_daily_slot_before_legacy_message_pool(
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

    from app.campaign_worker import _claim_next_job_sync, materialize_daily_plans

    assert materialize_daily_plans() == 1
    job = _claim_next_job_sync()

    assert isinstance(job, dict)
    assert job["text"] == "pinned slot"
    assert job["daily_plan_id"]
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


def test_manual_test_uses_the_claimed_daily_slot_when_library_is_published(
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

    from app.campaign_worker import materialize_daily_plans

    assert materialize_daily_plans() == 1
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
    assert send.await_args.kwargs["daily_plan_id"]
    assert send.await_args.kwargs["slot_id"]
