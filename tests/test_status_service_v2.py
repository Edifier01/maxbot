"""T18: scoped snapshots and bounded event streams."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from app.repositories.summary import SummaryRepository
from app.services.status import AuthorizationError, StatusService


def test_ten_subscribers_share_one_scoped_snapshot_and_safe_projection() -> None:
    calls: list[str] = []

    def provider(scope: str):
        calls.append(scope)
        return {
            "scope": scope,
            "revision": 4,
            "connections": [{"id": 1, "credential_ref": "vault:x", "password": "secret"}],
            "progress": {"accepted": 2, "unknown": 1},
        }

    service = StatusService(provider)
    viewers = [service.subscribe("tenant:1", actor_scope="tenant:1", role="user") for _ in range(10)]
    snapshots = [service.get_snapshot("tenant:1", projection="cabinet") for _ in viewers]
    assert len(calls) == 1
    assert all("credential_ref" not in item["connections"][0] for item in snapshots)
    assert all("password" not in item["connections"][0] for item in snapshots)
    assert all(item["progress"] == {"accepted": 2, "unknown": 1} for item in snapshots)


def test_event_envelope_sequence_and_resync_after_missed_events() -> None:
    service = StatusService(lambda _scope: {"revision": 1, "ok": True})
    subscriber = service.subscribe("tenant:1", actor_scope="tenant:1", role="admin", queue_size=1)
    service.publish_domain_event("tenant:1", "campaign_changed", {"state": "running"})
    service.publish_domain_event("tenant:1", "campaign_changed", {"state": "waiting"})

    async def read_one():
        return await subscriber.receive()

    first = asyncio.run(read_one())
    assert first.stream_id == "tenant:1"
    assert first.sequence in {1, 2}
    assert first.revision == first.sequence
    assert first.event_type in {"campaign_changed", "resync_required"}
    fresh = service.resync(subscriber)
    assert fresh["scope"] == "tenant:1"
    assert fresh["ok"] is True


def test_scope_authorization_is_checked_before_snapshot_or_subscription() -> None:
    service = StatusService(lambda _scope: {"ok": True})
    with pytest.raises(AuthorizationError):
        service.subscribe("tenant:1", actor_scope="tenant:2", role="user")
    with pytest.raises(AuthorizationError):
        service.get_snapshot("tenant:1", projection="cabinet", actor_scope="tenant:2")


def test_one_hundred_status_scope_connect_disconnect_cycles_are_retired() -> None:
    service = StatusService(lambda scope: {"scope": scope, "ok": True})
    for index in range(100):
        scope = f"tenant:{index}"
        service.subscribe(scope, actor_scope=scope, role="user")
        service.get_snapshot(scope, actor_scope=scope)
        service.close_scope(scope)

    assert service._subscribers == {}
    assert service._snapshot_cache == {}
    assert service._streams == {}


def test_summary_repository_is_read_only_and_keeps_library_separate_from_plan_counts() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE message_set_versions (
            scope TEXT, version_id TEXT, item_count INTEGER, is_current INTEGER,
            checksum TEXT, created_at TEXT
        );
        INSERT INTO message_set_versions VALUES ('tenant:1', 'v1', 5, 1, 'sha', 'now');
        CREATE TABLE profile_daily_plans (
            scope TEXT, profile_id INTEGER, target INTEGER, role TEXT,
            status TEXT, business_date TEXT
        );
        INSERT INTO profile_daily_plans VALUES ('tenant:1', 7, 5, 'active', 'active', '2026-09-20');
        """
    )
    before = connection.total_changes
    summary = SummaryRepository(connection).read("tenant:1")
    assert connection.total_changes == before
    assert summary["library_count"] == 5
    assert summary["plan_target"] == 5
    connection.close()
