"""Bounded per-session client leases for login/send/delete lifecycle paths."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
from typing import Any, Awaitable, Callable


class ClientCleanupError(RuntimeError):
    def __init__(self, message: str, *, outcome: str) -> None:
        self.outcome = outcome
        super().__init__(message)


@dataclass
class ClientLease:
    key: tuple[str, int]
    route_snapshot: object
    purpose: str
    client: Any
    _lock: asyncio.Lock
    outcome: str = "not_started"
    released: bool = False


class ClientManager:
    """Serialize clients by scoped profile and drain before runtime deletion."""

    def __init__(self, *, close_timeout: float = 15.0) -> None:
        self._locks: dict[tuple[str, int], asyncio.Lock] = {}
        self._active: dict[tuple[str, int], ClientLease] = {}
        self._deleting: set[tuple[str, int]] = set()
        self._close_timeout = max(0.1, float(close_timeout))

    def _lock_for(self, key: tuple[str, int]) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def acquire(
        self,
        scope: str,
        profile_id: int,
        route_snapshot: object,
        purpose: str,
        factory: Callable[[], Awaitable[Any] | Any],
    ) -> ClientLease:
        key = (str(scope), int(profile_id))
        if key in self._deleting:
            raise ClientCleanupError("profile_deletion_in_progress", outcome="unknown")
        lock = self._lock_for(key)
        await lock.acquire()
        if key in self._deleting:
            lock.release()
            raise ClientCleanupError("profile_deletion_in_progress", outcome="unknown")
        try:
            client = factory()
            if inspect.isawaitable(client):
                client = await client
        except BaseException:
            lock.release()
            raise
        lease = ClientLease(
            key=key,
            route_snapshot=route_snapshot,
            purpose=purpose,
            client=client,
            _lock=lock,
        )
        self._active[key] = lease
        return lease

    async def release(self, lease: ClientLease) -> None:
        if lease.released:
            return
        cleanup_error: BaseException | None = None
        try:
            close = getattr(lease.client, "close", None)
            if not callable(close):
                close = getattr(lease.client, "stop", None)
            if callable(close):
                await asyncio.wait_for(close(), timeout=self._close_timeout)
        except BaseException as exc:
            cleanup_error = exc
        finally:
            self._active.pop(lease.key, None)
            lease.released = True
            if lease._lock.locked():
                lease._lock.release()
        if cleanup_error is not None:
            raise ClientCleanupError(
                "client_cleanup_failed",
                outcome=lease.outcome,
            ) from cleanup_error

    def active(self, scope: str, profile_id: int) -> bool:
        return (str(scope), int(profile_id)) in self._active

    async def delete_profile_runtime(
        self,
        scope: str,
        profile_id: int,
        *,
        cancel_and_wait: Callable[[], Awaitable[None] | None],
        remove_runtime: Callable[[], Awaitable[None] | None],
    ) -> None:
        key = (str(scope), int(profile_id))
        if key in self._deleting:
            raise ClientCleanupError("profile_deletion_in_progress", outcome="unknown")
        self._deleting.add(key)
        try:
            result = cancel_and_wait()
            if inspect.isawaitable(result):
                await result
            if key in self._active:
                raise ClientCleanupError("client_still_active", outcome=self._active[key].outcome)
            result = remove_runtime()
            if inspect.isawaitable(result):
                await result
        finally:
            self._deleting.discard(key)
