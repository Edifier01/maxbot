"""Idempotent process shutdown: stop campaign work, then encrypt sessions.

Signal handlers must not encrypt or sys.exit while an event loop is running.
Lifespan (and tests) call graceful_shutdown() for the drain contract.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

_lock: asyncio.Lock | None = None
_finished = False
_encrypt_ran = False


def reset_test() -> None:
    global _lock, _finished, _encrypt_ran
    _lock = None
    _finished = False
    _encrypt_ran = False


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def note_signal(_signum: int | None = None) -> bool:
    """Sync SIGTERM/SIGINT path.

    Returns True only when there is no running loop (startup / post-serve) and
    the caller may encrypt + exit. Never encrypts itself.
    """
    from app.campaign_runtime import REGISTRY

    already = REGISTRY.app.shutting_down
    REGISTRY.app.shutting_down = True
    if already:
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return True
    if loop.is_running():
        return False
    return True


async def _cancel_background_tasks() -> None:
    from app.campaign_runtime import RUNTIME

    for task in (
        RUNTIME.watchdog_task,
        RUNTIME.scheduler_task,
        RUNTIME.backup_task,
        RUNTIME.ops_alert_task,
        RUNTIME.subscription_task,
    ):
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    RUNTIME.watchdog_task = RUNTIME.scheduler_task = RUNTIME.backup_task = None
    RUNTIME.ops_alert_task = RUNTIME.subscription_task = None


async def graceful_shutdown(
    *,
    encrypt: bool = True,
    cancel_background: bool | None = None,
    reason: str = "Остановка сервера",
) -> None:
    """Drain campaign workers, then encrypt sessions. Safe to call twice."""
    global _finished, _encrypt_ran

    from app.campaign_runtime import REGISTRY
    from app.campaign_worker import stop_all_workers

    REGISTRY.app.shutting_down = True
    async with _get_lock():
        if _finished:
            return
        import main as app_main

        do_bg = (
            (not app_main._is_test_mode())
            if cancel_background is None
            else cancel_background
        )
        if do_bg:
            await _cancel_background_tasks()
        await stop_all_workers(finish_status="stopped", reason=reason)
        if encrypt and not _encrypt_ran:
            app_main._encrypt_all_sessions()
            _encrypt_ran = True
        _finished = True


def handle_process_signal(signum: int, _frame: Any, *, encrypt_all, exit_fn, log) -> None:
    """Shared SIGTERM/SIGINT handler used by app.main and main.py."""
    if not note_signal(signum):
        log(f"Сигнал {signum}: остановка через lifespan, без аварийного выхода")
        return
    log(f"Сигнал {signum}: нет event loop — шифрование сессий и выход…")
    encrypt_all()
    exit_fn(0)
