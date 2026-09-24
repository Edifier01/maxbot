"""SIGTERM handler sets RUNTIME.shutting_down without AttributeError."""

from __future__ import annotations

import inspect


def test_app_main_uses_runtime_shutting_down():
    import app.main as entry

    src = inspect.getsource(entry.main)
    assert "handle_process_signal" in src
    assert "app_main._shutting_down" not in src


def test_weekly_claim_path_replaces_legacy_pool_completion_state():
    from app import campaign_worker as cw

    src = inspect.getsource(cw.claim_next_job) + inspect.getsource(cw._claim_next_job_sync)
    assert "_claim_weekly_job_sync" in src
    assert "main._campaign_goal" not in src
    assert "_reset_daily_counts" not in src
