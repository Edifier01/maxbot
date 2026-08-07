"""SIGTERM handler sets RUNTIME.shutting_down without AttributeError."""

from __future__ import annotations

import inspect


def test_app_main_uses_runtime_shutting_down():
    import app.main as entry

    src = inspect.getsource(entry.main)
    assert "RUNTIME.shutting_down" in src
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
