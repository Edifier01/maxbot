"""campaign_runtime + campaign_pacing unit tests."""

from __future__ import annotations

import asyncio
import importlib
import os
from unittest.mock import AsyncMock

import pytest
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
    monkeypatch.setattr(m, "_preflight_group_proxies", AsyncMock())
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(m, "_send_with_retry", send)

    from app.routes_campaign import campaign_test

    result = asyncio.run(campaign_test())
    assert result["ok"] is True
    assert send.await_args.kwargs["advance_queue"] is False
