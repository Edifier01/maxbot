"""In-memory worker/campaign runtime state (tasks, locks, pacing dicts).

Per-tenant worker runtimes in server mode; see docs/adr/001-tenant-worker-isolation.md.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_LOCAL_KEY = 0


@dataclass
class CampaignRuntime:
    tenant_id: int | None = None
    worker_ctx_snapshot: Any = None
    worker_task: asyncio.Task[Any] | None = None
    pool_tasks: list[asyncio.Task[Any]] = field(default_factory=list)
    worker_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    claim_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    worker_last_activity: float = 0.0
    current_campaign_id: int | None = None
    pool_done_announced: bool = False
    consecutive_errors: dict[int, int] = field(default_factory=dict)
    circuit_opened_at: dict[int, float] = field(default_factory=dict)
    human_burst_count: dict[int, int] = field(default_factory=dict)
    human_break_until: dict[int, datetime] = field(default_factory=dict)
    groups_in_flight: set[int] = field(default_factory=set)
    jobs_in_flight: int = 0
    profile_reserved: dict[int, int] = field(default_factory=dict)

    def touch_activity(self) -> None:
        self.worker_last_activity = time.monotonic()

    def worker_busy(self) -> bool:
        return self.worker_task is not None and not self.worker_task.done()

    def reset_test(self) -> None:
        self.worker_task = None
        self.pool_tasks = []
        self.current_campaign_id = None
        self.pool_done_announced = False
        self.worker_last_activity = 0.0
        self.worker_ctx_snapshot = None
        self.tenant_id = None
        self.consecutive_errors.clear()
        self.circuit_opened_at.clear()
        self.human_burst_count.clear()
        self.human_break_until.clear()
        self.groups_in_flight.clear()
        self.jobs_in_flight = 0
        self.profile_reserved.clear()


@dataclass
class _AppRuntime:
    """Process-wide: watchdog, scheduler, backup, shutdown flag."""

    watchdog_task: asyncio.Task[Any] | None = None
    scheduler_task: asyncio.Task[Any] | None = None
    backup_task: asyncio.Task[Any] | None = None
    subscription_task: asyncio.Task[Any] | None = None
    ops_alert_task: asyncio.Task[Any] | None = None
    shutting_down: bool = False

    def reset_test(self) -> None:
        self.watchdog_task = None
        self.scheduler_task = None
        self.backup_task = None
        self.subscription_task = None
        self.ops_alert_task = None
        self.shutting_down = False


class RuntimeRegistry:
    def __init__(self) -> None:
        self._app = _AppRuntime()
        self._workers: dict[int, CampaignRuntime] = {}

    @staticmethod
    def _key(tenant_id: int | None) -> int:
        return tenant_id if tenant_id is not None else _LOCAL_KEY

    @staticmethod
    def _tenant_from_key(key: int) -> int | None:
        return None if key == _LOCAL_KEY else key

    def worker_for(self, tenant_id: int | None) -> CampaignRuntime:
        key = self._key(tenant_id)
        rt = self._workers.get(key)
        if rt is None:
            rt = CampaignRuntime(tenant_id=tenant_id)
            self._workers[key] = rt
        return rt

    def worker(self) -> CampaignRuntime:
        try:
            from app.config import is_server_mode

            if not is_server_mode():
                return self.worker_for(None)
        except ImportError:
            return self.worker_for(None)
        from app.tenant import get_tenant_id

        return self.worker_for(get_tenant_id())

    def worker_items(self) -> list[tuple[int, CampaignRuntime]]:
        return list(self._workers.items())

    def drop_worker(self, tenant_id: int) -> None:
        """Forget stopped per-tenant runtime after permanent tenant deletion."""
        self._workers.pop(self._key(tenant_id), None)

    def reset_test(self) -> None:
        self._app.reset_test()
        self._workers.clear()
        from app.shutdown import reset_test as reset_shutdown

        reset_shutdown()

    @property
    def app(self) -> _AppRuntime:
        return self._app


REGISTRY = RuntimeRegistry()

_APP_ATTRS = frozenset(
    {
        "watchdog_task",
        "scheduler_task",
        "backup_task",
        "subscription_task",
        "ops_alert_task",
        "shutting_down",
    }
)


class _RuntimeProxy:
    """Routes worker fields to current tenant runtime; app fields to process runtime."""

    def reset_test(self) -> None:
        REGISTRY.reset_test()

    def __getattr__(self, name: str) -> Any:
        if name in _APP_ATTRS:
            return getattr(REGISTRY.app, name)
        return getattr(REGISTRY.worker(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in _APP_ATTRS:
            setattr(REGISTRY.app, name, value)
        else:
            setattr(REGISTRY.worker(), name, value)


RUNTIME = _RuntimeProxy()
