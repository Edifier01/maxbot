"""Per-tenant in-flight group lock: two workers must not send to the same group."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.campaign_runtime import REGISTRY, RUNTIME
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
    main_mod.set_setting("message_pick_mode", "round_robin")
    monkeypatch.setattr(main_mod, "load_message_pool", lambda: ["hello", "world", "third"])
    monkeypatch.setattr(main_mod, "_is_circuit_open", lambda _pid: False)
    monkeypatch.setattr(main_mod, "_can_send_in_group", lambda _p, _gid: True)
    yield main_mod
    sqlite_backend.reset_connections()
    REGISTRY.reset_test()
    main_mod._settings_cache.clear()


def _claim_job():
    """Same mark as async claim_next_job (sync body must not add)."""
    from app import campaign_worker as cw

    job = cw._claim_next_job_sync()
    if isinstance(job, dict):
        RUNTIME.groups_in_flight.add(int(job["group"]["id"]))
    return job


def _seed(m, group_ids: list[int], *, n_profiles: int = 1) -> None:
    with m._conn() as c:
        c.execute(
            "UPDATE queue_state SET running=1, profile_idx=0, message_idx=0, "
            "group_idx=0 WHERE id=1"
        )
        for gid in group_ids:
            c.execute(
                "INSERT INTO groups (id, name, proxy, is_active) VALUES (?, ?, ?, 1)",
                (gid, f"g{gid}", "socks5://proxy.example:1080"),
            )
        for i in range(n_profiles):
            pid = i + 1
            c.execute(
                "INSERT INTO profiles (id, phone, status) VALUES (?, ?, ?)",
                (pid, f"+7999000000{pid}", m.ProfileStatus.ACTIVE),
            )
            gid = group_ids[(i - 1) % len(group_ids)]
            c.execute(
                "INSERT INTO group_profiles "
                "(group_id, profile_id, order_index, is_enabled) "
                "VALUES (?, ?, 0, 1)",
                (gid, pid),
            )
            from app.repositories.weekly_schedule import WeeklyScheduleRepository

            weekly = WeeklyScheduleRepository(c)
            weekly.assign_profile(pid, gid)
            c.execute(
                "UPDATE profile_send_schedules SET send_weekday=? WHERE profile_id=?",
                (m._local_today().weekday(), pid),
            )
    from app.campaign_worker import materialize_weekly_plans

    materialize_weekly_plans()


def test_second_claim_skips_inflight_group(m):
    _seed(m, [1, 2])
    job1 = _claim_job()
    assert job1 is not None
    claimed_group = int(job1["group"]["id"])
    assert claimed_group in {1, 2}
    assert claimed_group in RUNTIME.groups_in_flight

    job2 = _claim_job()
    assert job2 == "WEEKLY_WAIT"
    assert RUNTIME.groups_in_flight == {claimed_group}


def test_only_group_inflight_returns_none(m):
    from app import campaign_worker as cw

    _seed(m, [1])
    RUNTIME.groups_in_flight.add(1)
    assert cw._claim_next_job_sync() in {"WEEKLY_WAIT", "WEEKLY_DONE"}


def test_release_allows_skipped_group_again(m):
    _seed(m, [1, 2])
    job1 = _claim_job()
    job2 = _claim_job()
    claimed_group = int(job1["group"]["id"])
    assert job2 == "WEEKLY_WAIT"
    RUNTIME.groups_in_flight.discard(claimed_group)
    job3 = _claim_job()
    assert job3 == "WEEKLY_WAIT"


def test_reset_test_clears_inflight():
    REGISTRY.reset_test()
    rt = REGISTRY.worker_for(None)
    rt.groups_in_flight.add(7)
    rt.jobs_in_flight = 3
    rt.profile_reserved[1] = 2
    rt.reset_test()
    assert rt.groups_in_flight == set()
    assert rt.jobs_in_flight == 0
    assert rt.profile_reserved == {}


def test_inflight_set_is_per_tenant():
    REGISTRY.reset_test()
    rt1 = REGISTRY.worker_for(1)
    rt2 = REGISTRY.worker_for(2)
    rt1.groups_in_flight.add(9)
    assert rt2.groups_in_flight == set()
    REGISTRY.reset_test()


def test_pool_size_one_claim_returns_only_group(m):
    _seed(m, [1])
    assert m._pool_size() == 1
    assert not RUNTIME.groups_in_flight
    job = _claim_job()
    assert job is not None
    assert int(job["group"]["id"]) == 1


def test_sync_claim_does_not_mark_inflight(m):
    from app import campaign_worker as cw

    _seed(m, [1])
    job = cw._claim_next_job_sync()
    assert job is not None
    assert int(job["group"]["id"]) == 1
    assert not RUNTIME.groups_in_flight


def test_async_claim_marks_inflight(m):
    from app import campaign_worker as cw

    _seed(m, [1])

    async def _run():
        job = await cw.claim_next_job()
        assert job is not None
        assert int(job["group"]["id"]) == 1
        assert 1 in RUNTIME.groups_in_flight
        assert RUNTIME.jobs_in_flight == 1
        assert RUNTIME.profile_reserved.get(int(job["profile"]["id"]), 0) == 1

    asyncio.run(_run())


def test_async_claim_does_not_leave_sqlite_work_in_background(m, monkeypatch):
    from app import campaign_worker as cw

    _seed(m, [1])

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("claim must finish on the event-loop thread")

    monkeypatch.setattr(cw.asyncio, "to_thread", forbidden)

    async def _run():
        job = await cw.claim_next_job()
        assert isinstance(job, dict)
        assert RUNTIME.jobs_in_flight == 1

    asyncio.run(_run())


def _queue_state(m):
    with m._conn() as c:
        row = c.execute(
            "SELECT profile_idx, message_idx, group_idx, message_bag "
            "FROM queue_state WHERE id=1"
        ).fetchone()
    return dict(row)


def test_safe_cancel_restores_sequential_claim(m):
    from app import campaign_worker as cw
    from app.campaign_send import SendTracker

    _seed(m, [1])
    before = _queue_state(m)
    job = cw._claim_next_job_sync()
    assert _queue_state(m) == before

    cw._restore_claim(job, SendTracker())

    assert _queue_state(m) == before


def test_safe_cancel_restores_exact_random_bag(m):
    from app import campaign_worker as cw
    from app.campaign_send import SendTracker

    m.set_setting("message_pick_mode", "random_norepeat")
    _seed(m, [1])
    with m._conn() as c:
        c.execute(
            "UPDATE queue_state SET message_bag=?, message_idx=0 WHERE id=1",
            (json.dumps([2, 0, 1]),),
        )
    before = _queue_state(m)
    job = cw._claim_next_job_sync()
    assert _queue_state(m) == before

    cw._restore_claim(job, SendTracker())

    assert _queue_state(m) == before


def test_unknown_send_does_not_restore_claim(m):
    from app import campaign_worker as cw
    from app.campaign_send import SendTracker

    _seed(m, [1])
    before = _queue_state(m)
    job = cw._claim_next_job_sync()
    claimed = _queue_state(m)
    tracker = SendTracker()
    tracker.mark_unknown("network outcome unknown")

    cw._restore_claim(job, tracker)

    assert claimed == before
    assert _queue_state(m) == claimed


def test_poolworker_releases_inflight_on_cancel(m, monkeypatch):
    from app import campaign_worker as cw

    RUNTIME.groups_in_flight.add(1)
    RUNTIME.jobs_in_flight = 1
    RUNTIME.profile_reserved[1] = 1
    job = {
        "profile": {"id": 1},
        "group": {"id": 1, "name": "g"},
        "text": "hi",
        "mi": 0,
        "pi": 0,
        "gi_next": 0,
        "mi_next": 0,
    }

    async def fake_claim():
        return job

    async def boom(*_a, **_k):
        raise asyncio.CancelledError

    async def no_window():
        return False

    async def no_presence():
        return None

    monkeypatch.setattr(cw, "claim_next_job", fake_claim)
    monkeypatch.setattr(cw, "send_with_retry", boom)
    monkeypatch.setattr(m, "_wait_if_outside_send_window", no_window)
    monkeypatch.setattr(m, "_maybe_idle_presence", no_presence)
    monkeypatch.setattr(m, "append_log", lambda *_a, **_k: None)
    monkeypatch.setattr(m, "_touch_worker_activity", lambda: None)

    async def _run():
        with tenant_scope(tenant_id=None, role="user"):
            await cw.poolworker_loop(1)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run())
    assert 1 not in RUNTIME.groups_in_flight
    assert RUNTIME.jobs_in_flight == 0
    assert 1 not in RUNTIME.profile_reserved


def test_claim_skips_profile_with_weekly_send_already_used(m):
    from app import campaign_worker as cw

    _seed(m, [1, 2], n_profiles=2)
    today = m._local_today().isoformat()
    with m._conn() as c:
        c.execute(
            "INSERT INTO send_log(profile_id, group_id, message_idx, status, sent_at) "
            "VALUES (1, 1, 0, 'sent', ?)",
            (today + " 12:00:00",),
        )
    job = cw._claim_next_job_sync()
    assert job is not None
    assert int(job["profile"]["id"]) == 2


def test_weekly_slot_is_available_independent_of_legacy_message_bag(m):
    from app import campaign_worker as cw

    m.set_setting("message_pick_mode", "random_norepeat")
    _seed(m, [1])
    with m._conn() as c:
        c.execute(
            "UPDATE queue_state SET message_bag='[]', message_idx=? WHERE id=1",
            (3,),
        )
    RUNTIME.jobs_in_flight = 2
    RUNTIME.pool_done_announced = False
    job = cw._claim_next_job_sync()
    assert isinstance(job, dict)
    assert job["weekly_plan"] is True
    assert RUNTIME.pool_done_announced is False
