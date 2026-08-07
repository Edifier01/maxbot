"""campaign_runtime + campaign_pacing unit tests."""

from __future__ import annotations

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
