"""Idempotent process shutdown: stop campaign work, then encrypt sessions.

Signal handlers must not encrypt or sys.exit while an event loop is running.
Lifespan (and tests) call graceful_shutdown() for the drain contract.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

_lock: asyncio.Lock | None = None
_finished = False
_encrypt_ran = False


def _grace_seconds() -> float:
    try:
        value = float(os.environ.get("MAX_SHUTDOWN_GRACE_SECONDS", "45"))
    except ValueError:
        value = 45.0
    return min(max(value, 5.0), 120.0)


async def _bounded_step(label: str, operation: Any, *, timeout: float) -> bool:
    try:
        await asyncio.wait_for(operation, timeout=timeout)
    except asyncio.CancelledError:
        raise
    except BaseException as exc:
        try:
            import main as app_main

            app_main.append_log(f"Shutdown: {label} не завершён в срок/с ошибкой: {exc}")
        except BaseException:
            pass
        return False
    return True


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
        RUNTIME.onboarding_cleanup_task,
    ):
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(asyncio.shield(task), timeout=_grace_seconds())
    RUNTIME.watchdog_task = RUNTIME.scheduler_task = RUNTIME.backup_task = None
    RUNTIME.ops_alert_task = RUNTIME.subscription_task = None
    RUNTIME.onboarding_cleanup_task = None


async def graceful_shutdown(
    *,
    encrypt: bool = True,
    cancel_background: bool | None = None,
    reason: str = "Остановка сервера",
) -> None:
    """Drain all owned work in a bounded order, then encrypt sessions."""
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
            await _bounded_step(
                "фоновые задачи",
                _cancel_background_tasks(),
                timeout=_grace_seconds(),
            )
        await _bounded_step(
            "воркеры рассылки",
            stop_all_workers(finish_status="stopped", reason=reason),
            timeout=_grace_seconds(),
        )
        await _bounded_step(
            "login tasks",
            app_main._cancel_all_login_tasks(),
            timeout=_grace_seconds(),
        )
        if app_main._is_server_mode():
            from app.routes_onboarding import cancel_all_onboarding_auth

            await _bounded_step(
                "onboarding auth tasks",
                cancel_all_onboarding_auth(),
                timeout=_grace_seconds(),
            )
        manager = getattr(app_main, "_client_manager", None)
        if manager is not None:
            await _bounded_step(
                "client leases",
                manager.drain(timeout=_grace_seconds()),
                timeout=_grace_seconds(),
            )
        if encrypt and not _encrypt_ran:
            if app_main._is_test_mode():
                # The test runner's Python 3.12 asyncio shutdown can wait
                # forever for its default executor after a completed
                # ``to_thread`` call. Test mode has no production event-loop
                # workload, so keep the same operation deterministic and
                # inline while retaining the bounded worker path in prod.
                async def _reseal_inline() -> None:
                    app_main._encrypt_all_sessions()

                reseal_operation = _reseal_inline()
            else:
                reseal_operation = asyncio.to_thread(app_main._encrypt_all_sessions)
            if await _bounded_step(
                "reseal sessions",
                reseal_operation,
                timeout=_grace_seconds(),
            ):
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
