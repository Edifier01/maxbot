"""Scoped status snapshots and bounded domain-event streams."""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable


class AuthorizationError(PermissionError):
    pass


@dataclass(frozen=True)
class EventEnvelope:
    stream_id: str
    sequence: int
    revision: int
    generated_at: str
    event_type: str
    payload: dict[str, object]


class StatusSubscription:
    def __init__(self, service: "StatusService", scope: str, role: str, queue_size: int) -> None:
        self.service = service
        self.scope = scope
        self.role = role
        self.queue: asyncio.Queue[EventEnvelope] = asyncio.Queue(maxsize=max(1, queue_size))
        self.closed = False

    async def receive(self) -> EventEnvelope:
        return await self.queue.get()

    def _push(self, event: EventEnvelope) -> None:
        if self.closed:
            return
        if self.queue.full():
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            event = EventEnvelope(
                stream_id=self.scope,
                sequence=event.sequence,
                revision=event.revision,
                generated_at=event.generated_at,
                event_type="resync_required",
                payload={"reason": "subscriber_backlog_bounded"},
            )
        self.queue.put_nowait(event)


class StatusService:
    def __init__(self, provider: Callable[[str], dict[str, object]]) -> None:
        self.provider = provider
        self._snapshot_cache: dict[str, dict[str, object]] = {}
        self._streams: dict[str, dict[str, object]] = {}
        self._subscribers: dict[str, list[StatusSubscription]] = {}

    def subscribe(
        self,
        scope: str,
        *,
        actor_scope: str | None,
        role: str,
        queue_size: int = 32,
    ) -> StatusSubscription:
        self._authorize(scope, actor_scope)
        subscription = StatusSubscription(self, scope, role, queue_size)
        self._subscribers.setdefault(scope, []).append(subscription)
        self._streams.setdefault(scope, {"sequence": 0, "revision": 0})
        return subscription

    def get_snapshot(
        self,
        scope: str,
        *,
        projection: str = "cabinet",
        actor_scope: str | None = None,
    ) -> dict[str, object]:
        self._authorize(scope, actor_scope)
        if scope not in self._snapshot_cache:
            raw = copy.deepcopy(self.provider(scope))
            if not isinstance(raw, dict):
                raw = {}
            raw["scope"] = scope
            raw.setdefault("source_time", datetime.now(timezone.utc).isoformat())
            self._snapshot_cache[scope] = raw
        snapshot = copy.deepcopy(self._snapshot_cache[scope])
        if projection == "cabinet":
            return self._redact(snapshot)
        if projection != "admin":
            raise ValueError("unsupported status projection")
        return snapshot

    def invalidate(self, scope: str) -> None:
        self._snapshot_cache.pop(scope, None)

    def publish_domain_event(
        self, scope: str, event_type: str, payload: dict[str, object]
    ) -> EventEnvelope:
        stream = self._streams.setdefault(scope, {"sequence": 0, "revision": 0})
        stream["sequence"] = int(stream["sequence"]) + 1
        stream["revision"] = int(stream["revision"]) + 1
        event = EventEnvelope(
            stream_id=scope,
            sequence=int(stream["sequence"]),
            revision=int(stream["revision"]),
            generated_at=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            payload=copy.deepcopy(payload),
        )
        for subscriber in list(self._subscribers.get(scope, [])):
            subscriber._push(event)
        return event

    def resync(self, subscription: StatusSubscription) -> dict[str, object]:
        if subscription.closed:
            raise AuthorizationError("subscription_closed")
        return self.get_snapshot(
            subscription.scope,
            projection="admin" if subscription.role == "admin" else "cabinet",
            actor_scope=subscription.scope,
        )

    def close_scope(self, scope: str) -> None:
        for subscription in self._subscribers.pop(scope, []):
            subscription.closed = True
        self._snapshot_cache.pop(scope, None)
        self._streams.pop(scope, None)

    @staticmethod
    def _authorize(scope: str, actor_scope: str | None) -> None:
        if actor_scope is not None and actor_scope != scope:
            raise AuthorizationError("scope_forbidden")

    @classmethod
    def _redact(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: cls._redact(item)
                for key, item in value.items()
                if key.lower() not in {
                    "credential_ref", "password", "token", "secret", "session_cookie"
                }
            }
        if isinstance(value, list):
            return [cls._redact(item) for item in value]
        return value
