"""Per-tenant in-flight group lock: two workers must not send to the same group."""

from __future__ import annotations

import asyncio

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
    main_mod.set_setting("campaign_goal", "daily_limits")
    main_mod.set_setting("role_plan_enabled", "0")
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
                "INSERT INTO groups (id, name, is_active) VALUES (?, ?, 1)",
                (gid, f"g{gid}"),
            )
        for i in range(n_profiles):
            pid = i + 1
            c.execute(
                "INSERT INTO profiles (id, phone, status) VALUES (?, ?, ?)",
                (pid, f"+7999000000{pid}", m.ProfileStatus.ACTIVE),
            )
            for gid in group_ids:
                c.execute(
                    "INSERT INTO group_profiles "
                    "(group_id, profile_id, order_index, is_enabled) "
                    "VALUES (?, ?, 0, 1)",
                    (gid, pid),
                )


def test_second_claim_skips_inflight_group(m):
    _seed(m, [1, 2])
    job1 = _claim_job()
    assert job1 is not None
    assert int(job1["group"]["id"]) == 1
    assert 1 in RUNTIME.groups_in_flight

    job2 = _claim_job()
    assert job2 is not None
    assert int(job2["group"]["id"]) == 2
    assert RUNTIME.groups_in_flight == {1, 2}


def test_only_group_inflight_returns_none(m):
    from app import campaign_worker as cw

    _seed(m, [1])
    RUNTIME.groups_in_flight.add(1)
    assert cw._claim_next_job_sync() is None


def test_release_allows_skipped_group_again(m):
    _seed(m, [1, 2])
    job1 = _claim_job()
    job2 = _claim_job()
    assert int(job1["group"]["id"]) == 1
    assert int(job2["group"]["id"]) == 2
    RUNTIME.groups_in_flight.discard(1)
    job3 = _claim_job()
    assert job3 is not None
    assert int(job3["group"]["id"]) == 1


def test_reset_test_clears_inflight():
    REGISTRY.reset_test()
    rt = REGISTRY.worker_for(None)
    rt.groups_in_flight.add(7)
    rt.reset_test()
    assert rt.groups_in_flight == set()


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

    asyncio.run(_run())


def test_cancelled_to_thread_does_not_mark(m, monkeypatch):
    from app import campaign_worker as cw

    _seed(m, [1])

    async def drop_result(fn, /, *args, **kwargs):
        fn(*args, **kwargs)
        raise asyncio.CancelledError

    monkeypatch.setattr(cw.asyncio, "to_thread", drop_result)

    async def _run():
        with pytest.raises(asyncio.CancelledError):
            await cw.claim_next_job()
        assert not RUNTIME.groups_in_flight

    asyncio.run(_run())


def test_poolworker_releases_inflight_on_cancel(m, monkeypatch):
    from app import campaign_worker as cw

    RUNTIME.groups_in_flight.add(1)
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
