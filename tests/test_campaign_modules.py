"""campaign_runtime + campaign_pacing unit tests."""

from __future__ import annotations

import asyncio
import importlib
import os
from unittest.mock import AsyncMock

import pytest


def _mock_weekly_test_slot(monkeypatch, profile, group):
    from app import campaign_worker

    job = {
        "profile": profile,
        "group": group,
        "text": "hello",
        "slot_id": "weekly-test-slot",
        "weekly_plan": True,
    }
    monkeypatch.setattr(campaign_worker, "materialize_weekly_plans", lambda: 1)
    monkeypatch.setattr(campaign_worker, "_claim_weekly_job_sync", lambda: job)
    monkeypatch.setattr(campaign_worker, "_finalize_weekly_job", lambda *_args: None)
    return job
from fastapi import HTTPException

from app import campaign_pacing


def test_runtime_reset_test():
    from app.campaign_runtime import REGISTRY

    REGISTRY.reset_test()
    rt = REGISTRY.worker_for(None)
    rt.consecutive_errors[1] = 3
    rt.worker_last_activity = 99.0
    REGISTRY.reset_test()
    rt2 = REGISTRY.worker_for(None)
    assert rt2.consecutive_errors == {}
    assert rt2.worker_last_activity == 0.0


def test_circuit_breaker_opens_and_closes():
    from app.campaign_runtime import REGISTRY

    REGISTRY.reset_test()
    logs: list[str] = []

    campaign_pacing.on_error(
        7,
        persist=lambda _pid: None,
        log=logs.append,
        setting_float=lambda _k, d: d,
        max_consecutive_errors=3,
        default_circuit_minutes=30.0,
    )
    campaign_pacing.on_error(
        7,
        persist=lambda _pid: None,
        log=logs.append,
        setting_float=lambda _k, d: d,
        max_consecutive_errors=3,
        default_circuit_minutes=30.0,
    )
    campaign_pacing.on_error(
        7,
        persist=lambda _pid: None,
        log=logs.append,
        setting_float=lambda _k, d: d,
        max_consecutive_errors=3,
        default_circuit_minutes=30.0,
    )
    assert campaign_pacing.is_circuit_open(
        7,
        persist=lambda _pid: None,
        log=logs.append,
        setting_float=lambda _k, d: 0.0,
        max_consecutive_errors=3,
        default_circuit_minutes=30.0,
    )
    campaign_pacing.on_success(7, lambda _pid: None)
    assert not campaign_pacing.is_circuit_open(
        7,
        persist=lambda _pid: None,
        log=logs.append,
        setting_float=lambda _k, d: d,
        max_consecutive_errors=3,
        default_circuit_minutes=30.0,
    )


@pytest.fixture
def setup_local(tmp_path, monkeypatch):
    prev_server = os.environ.get("MAX_SERVER_MODE")
    prev_test = os.environ.get("MAX_TEST")
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    # main reload preserves sqlite_backend's process-level local connection;
    # close it before this fixture switches to its isolated temporary root.
    m.reset_test_runtime()
    m.init_db()
    try:
        yield m
    finally:
        if prev_server is None:
            os.environ.pop("MAX_SERVER_MODE", None)
        else:
            os.environ["MAX_SERVER_MODE"] = prev_server
        if prev_test is None:
            os.environ.pop("MAX_TEST", None)
        else:
            os.environ["MAX_TEST"] = prev_test
        importlib.reload(cfg)
        importlib.reload(m)


def test_campaign_test_busy_conflict(setup_local, monkeypatch):
    m = setup_local
    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m.RUNTIME, "worker_busy", lambda: True)

    from app.routes_campaign import campaign_test

    with pytest.raises(HTTPException) as ei:
        asyncio.run(campaign_test())
    assert ei.value.status_code in (409, 400)
    assert "кампания" in str(ei.value.detail).lower()


def test_campaign_test_idle_does_not_advance_queue(setup_local, monkeypatch):
    m = setup_local
    group = {"id": 1, "name": "G1"}
    profile = {"id": 1, "phone": "+79991112233"}
    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m.RUNTIME, "worker_busy", lambda: False)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["hello"])
    monkeypatch.setattr(m, "_active_groups", lambda: [group])
    monkeypatch.setattr(m, "_active_profiles_for_group", lambda _gid: [profile])
    monkeypatch.setattr(m, "_is_circuit_open", lambda _pid: False)
    monkeypatch.setattr(m, "_can_send_in_group", lambda _p, _gid: True)
    from app import routes_campaign
    _mock_weekly_test_slot(monkeypatch, profile, group)

    monkeypatch.setattr(routes_campaign.m, "_preflight_group_proxies", AsyncMock(), raising=False)
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(routes_campaign.m, "_send_with_retry", send, raising=False)

    from app.routes_campaign import campaign_test

    result = asyncio.run(campaign_test(request_id="same-test"))
    repeated = asyncio.run(campaign_test(request_id="same-test"))
    assert result["ok"] is True
    assert repeated["idempotent"] is True
    assert send.await_count == 1
    assert send.await_args.kwargs["advance_queue"] is False


def test_campaign_test_waits_for_message_pool_publication_lock(setup_local, monkeypatch):
    m = setup_local
    group = {"id": 1, "name": "G1"}
    profile = {"id": 1, "phone": "+79991112233"}
    loaded: list[str] = []
    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m.RUNTIME, "worker_busy", lambda: False)

    def load_pool():
        loaded.append("load")
        return ["hello"]

    monkeypatch.setattr(m, "load_message_pool", load_pool)
    monkeypatch.setattr(m, "_active_groups", lambda: [group])
    monkeypatch.setattr(m, "_active_profiles_for_group", lambda _gid: [profile])
    monkeypatch.setattr(m, "_is_circuit_open", lambda _pid: False)
    monkeypatch.setattr(m, "_can_send_in_group", lambda _p, _gid: True)
    monkeypatch.setattr(
        m, "_require_profile_runtime_available", lambda _pid: None
    )
    from app import routes_campaign
    from app.campaign_runtime import REGISTRY
    _mock_weekly_test_slot(monkeypatch, profile, group)

    monkeypatch.setattr(routes_campaign.m, "_preflight_group_proxies", AsyncMock())
    monkeypatch.setattr(
        routes_campaign.m, "_send_with_retry", AsyncMock(return_value=True)
    )

    async def scenario():
        lock = REGISTRY.app.message_pool_lock
        await lock.acquire()
        task = asyncio.create_task(
            routes_campaign.campaign_test(request_id="test-library-lock")
        )
        try:
            await asyncio.sleep(0)
            assert not task.done()
            assert loaded == []
        finally:
            lock.release()
        return await task

    result = asyncio.run(scenario())
    assert result["ok"] is True
    assert loaded == ["load"]


def test_campaign_test_does_not_report_success_after_stop_fence(setup_local, monkeypatch):
    m = setup_local
    group = {"id": 1, "name": "G1"}
    profile = {"id": 1, "phone": "+79991112233"}
    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m.RUNTIME, "worker_busy", lambda: False)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["hello"])
    monkeypatch.setattr(m, "_active_groups", lambda: [group])
    monkeypatch.setattr(m, "_active_profiles_for_group", lambda _gid: [profile])
    monkeypatch.setattr(m, "_is_circuit_open", lambda _pid: False)
    monkeypatch.setattr(m, "_can_send_in_group", lambda _p, _gid: True)
    monkeypatch.setattr(
        m, "_require_profile_runtime_available", lambda _pid: None
    )
    from app import routes_campaign
    from app.routes_campaign import CampaignCommandCoordinator
    _mock_weekly_test_slot(monkeypatch, profile, group)

    monkeypatch.setattr(routes_campaign.m, "_preflight_group_proxies", AsyncMock())

    async def send_then_stop(*_args, **_kwargs):
        CampaignCommandCoordinator(m._conn(), scope="local").stop("stop-race")
        return True

    send = AsyncMock(side_effect=send_then_stop)
    monkeypatch.setattr(routes_campaign.m, "_send_with_retry", send)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(routes_campaign.campaign_test(request_id="test-stop-race"))
    assert caught.value.status_code == 409
    assert caught.value.detail == {"state": "fenced_by_stop"}
    send.assert_awaited_once()


def test_campaign_test_reports_daily_reservation_conflict(setup_local, monkeypatch):
    m = setup_local
    group = {"id": 1, "name": "G1"}
    profile = {"id": 1, "phone": "+79991112233"}
    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m.RUNTIME, "worker_busy", lambda: False)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["hello"])
    monkeypatch.setattr(m, "_active_groups", lambda: [group])
    monkeypatch.setattr(m, "_active_profiles_for_group", lambda _gid: [profile])
    monkeypatch.setattr(m, "_is_circuit_open", lambda _pid: False)
    monkeypatch.setattr(m, "_can_send_in_group", lambda _p, _gid: True)
    from app import routes_campaign
    from app.campaign_send import DailyReservationUnavailable
    _mock_weekly_test_slot(monkeypatch, profile, group)

    monkeypatch.setattr(routes_campaign.m, "_preflight_group_proxies", AsyncMock())

    async def unavailable(*_args, **kwargs):
        kwargs["tracker"].mark_failed_unsent(DailyReservationUnavailable.code)
        return False

    monkeypatch.setattr(routes_campaign.m, "_send_with_retry", unavailable)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(routes_campaign.campaign_test())
    assert caught.value.status_code == 409
    assert "недельный слот" in str(caught.value.detail).lower()
