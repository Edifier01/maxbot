"""SIGTERM handler sets RUNTIME.shutting_down without AttributeError."""

from __future__ import annotations

import asyncio
import inspect


def test_app_main_uses_runtime_shutting_down():
    import app.main as entry

    src = inspect.getsource(entry.main)
    assert "handle_process_signal" in src
    assert "app_main._shutting_down" not in src


def test_pool_done_announced_uses_runtime():
    from app.campaign_runtime import RUNTIME
    from app import campaign_worker as cw

    RUNTIME.pool_done_announced = False
    RUNTIME.pool_done_announced = True
    assert RUNTIME.pool_done_announced is True
    src = inspect.getsource(cw.claim_next_job) + inspect.getsource(cw._claim_next_job_sync)
    assert "_pool_done_announced" not in src
    assert "RUNTIME.pool_done_announced" in src


def test_shutdown_drains_workers_before_encrypting_sessions(monkeypatch):
    from app import campaign_worker
    from app.campaign_runtime import REGISTRY
    from app.shutdown import graceful_shutdown, note_signal, reset_test
    import main as app_main

    events: list[str] = []

    async def stop_workers(**_kwargs):
        events.append("stop-workers")

    def encrypt_sessions():
        events.append("encrypt-sessions")

    async def scenario():
        assert note_signal(15) is False
        await graceful_shutdown(cancel_background=False)

    reset_test()
    REGISTRY.reset_test()
    monkeypatch.setattr(campaign_worker, "stop_all_workers", stop_workers)
    monkeypatch.setattr(app_main, "_encrypt_all_sessions", encrypt_sessions)
    try:
        asyncio.run(scenario())
        assert events == ["stop-workers", "encrypt-sessions"]
    finally:
        reset_test()
        REGISTRY.reset_test()
