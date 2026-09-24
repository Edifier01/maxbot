"""T08: exclusive client leases drain before deletion and preserve outcomes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest


@dataclass
class _Client:
    closed: bool = False
    close_calls: int = 0
    fail_close: bool = False

    async def close(self) -> None:
        self.close_calls += 1
        if self.fail_close:
            raise OSError("close failed")
        self.closed = True


def test_same_session_never_has_two_clients() -> None:
    from app.services.client_manager import ClientManager

    manager = ClientManager()
    created: list[_Client] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def factory() -> _Client:
        client = _Client()
        created.append(client)
        entered.set()
        await release.wait()
        return client

    async def run() -> None:
        first_task = asyncio.create_task(
            manager.acquire("tenant:1", 7, "route-1", "send", factory)
        )
        await entered.wait()
        second_task = asyncio.create_task(
            manager.acquire("tenant:1", 7, "route-1", "login", factory)
        )
        await asyncio.sleep(0)
        assert len(created) == 1
        release.set()
        first = await first_task
        await manager.release(first)
        second = await second_task
        await manager.release(second)

    asyncio.run(run())
    assert len(created) == 2


def test_shutdown_cancels_login_tasks_and_is_idempotent() -> None:
    import main
    from app import shutdown
    from app.campaign_runtime import REGISTRY

    async def run() -> None:
        REGISTRY.reset_test()
        main._login_tasks.clear()
        main._client_manager = None
        shutdown.reset_test()
        stopped = asyncio.Event()

        async def login_task() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        task = asyncio.create_task(login_task())
        await asyncio.sleep(0)
        main._login_tasks["fixture"] = task
        await shutdown.graceful_shutdown(encrypt=False, cancel_background=False)
        assert stopped.is_set()
        assert main._login_tasks == {}
        await shutdown.graceful_shutdown(encrypt=False, cancel_background=False)

    asyncio.run(run())


def test_test_mode_shutdown_does_not_leave_default_executor_pending(monkeypatch) -> None:
    monkeypatch.setenv("MAX_TEST", "1")
    import main
    from app import shutdown
    from app.campaign_runtime import REGISTRY

    calls: list[str] = []

    async def run() -> None:
        REGISTRY.reset_test()
        shutdown.reset_test()
        main._client_manager = None
        monkeypatch.setattr(
            main, "_encrypt_all_sessions", lambda: calls.append("resealed")
        )
        await asyncio.wait_for(shutdown.graceful_shutdown(), timeout=1)

    asyncio.run(run())
    assert calls == ["resealed"]


def test_close_failure_keeps_accepted_outcome() -> None:
    from app.services.client_manager import ClientCleanupError, ClientManager

    async def run() -> None:
        manager = ClientManager()
        client = _Client(fail_close=True)
        lease = await manager.acquire(
            "tenant:1", 7, "route-1", "send", lambda: _ready(client)
        )
        lease.outcome = "accepted"
        with pytest.raises(ClientCleanupError) as caught:
            await manager.release(lease)
        assert caught.value.outcome == "accepted"
        assert manager.active("tenant:1", 7) is False

    async def _ready(client: _Client) -> _Client:
        return client

    asyncio.run(run())


def test_deleting_profile_rejects_new_client_acquisition() -> None:
    from app.services.client_manager import ClientCleanupError, ClientManager

    async def run() -> None:
        manager = ClientManager(delete_timeout=2)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def cancel_and_wait() -> None:
            entered.set()
            await release.wait()

        deleting = asyncio.create_task(
            manager.delete_profile_runtime(
                "local",
                7,
                cancel_and_wait=cancel_and_wait,
                remove_runtime=lambda: None,
            )
        )
        await entered.wait()
        with pytest.raises(ClientCleanupError, match="profile_deletion_in_progress"):
            await manager.acquire("local", 7, {}, "send", lambda: object())
        release.set()
        await deleting

    asyncio.run(run())


def test_delete_waits_for_task_before_rmtree() -> None:
    from app.services.client_manager import ClientManager

    async def run() -> None:
        manager = ClientManager()
        client = _Client()
        lease = await manager.acquire(
            "tenant:1", 7, "route-1", "login", lambda: _ready(client)
        )
        order: list[str] = []

        async def cancel_and_wait() -> None:
            order.append("cancel_wait")
            await manager.release(lease)

        await manager.delete_profile_runtime(
            "tenant:1",
            7,
            cancel_and_wait=cancel_and_wait,
            remove_runtime=lambda: order.append("rmtree"),
        )
        assert order == ["cancel_wait", "rmtree"]
        assert client.closed is True

    async def _ready(client: _Client) -> _Client:
        return client

    asyncio.run(run())
