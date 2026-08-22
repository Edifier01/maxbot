"""Pause must clear auto_run; start / retry / schedule-start enable daily continue."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.campaign_runtime import REGISTRY
from app.tenant import tenant_scope


@pytest.fixture
def m(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_DATA", str(tmp_path / "data"))
    import app.sqlite_backend as sqlite_backend
    import main as main_mod

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


def test_retry_failed_sets_auto_run(m, monkeypatch):
    m.set_setting("auto_run", "0")
    with m._conn() as c:
        c.execute("INSERT INTO profiles (id, phone) VALUES (1, '+79000000001')")
        c.execute("INSERT INTO groups (id, name) VALUES (1, 'retry-group')")
        c.execute(
            "INSERT INTO send_log (profile_id, group_id, message_idx, status) "
            "VALUES (1, 1, 4, 'failed')"
        )

    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)
    monkeypatch.setattr(m, "_preflight_group_proxies", AsyncMock())
    start_mock = AsyncMock()
    monkeypatch.setattr(m, "_start_worker", start_mock)

    from app.routes_campaign import campaign_retry_failed

    result = asyncio.run(campaign_retry_failed())
    assert result["ok"] is True
    assert result["message_idx"] == 4
    assert m.get_setting("auto_run") == "1"
    start_mock.assert_awaited_once()
    assert _queue_indices(m)[1] == 4


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

    start_mock = AsyncMock()
    monkeypatch.setattr(cw, "start_worker", start_mock)
    REGISTRY.reset_test()

    asyncio.run(cw.scheduler_tick())

    assert m.get_setting("auto_run") == "1"
    start_mock.assert_awaited_once()
    assert start_mock.await_args.kwargs["scheduled_for"] == past
    with m._conn() as c:
        row = c.execute("SELECT enabled FROM campaign_schedule WHERE id=1").fetchone()
    assert int(row["enabled"]) == 0


def test_try_auto_resume_skips_expired_subscription(m, monkeypatch):
    import app.db_pg as db_pg

    m.set_setting("auto_run", "1")
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
            resumed = await m._try_auto_resume(log_prefix="Автовозобновление")
            return resumed, m.get_setting("auto_run")

    resumed, auto_run = asyncio.run(_run())
    assert resumed is False
    assert auto_run == "0"
    start_mock.assert_not_awaited()


def test_scheduler_tick_skips_expired_subscription(m, monkeypatch):
    import app.campaign_worker as cw
    import app.db_pg as db_pg

    m.set_setting("auto_run", "1")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with m._conn() as c:
        c.execute(
            "UPDATE campaign_schedule SET enabled=1, start_at=? WHERE id=1",
            (past,),
        )

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
    start_mock.assert_not_awaited()


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
