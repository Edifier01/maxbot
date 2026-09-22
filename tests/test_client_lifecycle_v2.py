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
