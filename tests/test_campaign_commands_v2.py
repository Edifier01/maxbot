"""T14: read-only preview and persisted Start/Stop fencing."""

from __future__ import annotations

import sqlite3
import asyncio
import importlib
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.routes_campaign import (
    CampaignCommandCoordinator,
    CommandResult,
    ReadinessReport,
    build_readiness,
)


def _coordinator() -> tuple[sqlite3.Connection, CampaignCommandCoordinator]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    return connection, CampaignCommandCoordinator(connection, scope="tenant:1")


def _ready() -> ReadinessReport:
    return build_readiness(
        version="v2",
        scope="tenant:1",
        checks={"subscription": True, "ban": True, "library": True, "route": True},
        selection={"profiles": [1, 2], "targets": {"1": 5, "2": 7}},
    )


def test_preview_is_a_data_snapshot_and_does_not_write_or_call_sdk() -> None:
    connection, coordinator = _coordinator()
    try:
        report = _ready()
        assert report.ready is True
        assert coordinator.preview(report) == report
        assert connection.execute(
            "SELECT COUNT(*) FROM campaign_control"
        ).fetchone()[0] == 1
        # The control row is created by coordinator construction only; preview
        # itself does not create a campaign or an operation.
        assert connection.execute(
            "SELECT COUNT(*) FROM campaign_command_receipts"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_identical_start_command_is_idempotent() -> None:
    connection, coordinator = _coordinator()
    try:
        pending = coordinator.begin_start("req-start", _ready())
        repeated = coordinator.begin_start("req-start", _ready())
        assert isinstance(pending, CommandResult)
        assert repeated == pending
        assert pending.state == "preflight"
        assert connection.execute(
            "SELECT COUNT(*) FROM campaign_command_receipts"
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_stop_persists_fence_before_pending_start_can_complete() -> None:
    connection, coordinator = _coordinator()
    try:
        pending = coordinator.begin_start("req-start", _ready())
        stopped = coordinator.stop("req-stop")
        completed = coordinator.complete_start("req-start")
        assert pending.state == "preflight"
        assert stopped.accepted is True
        assert stopped.state == "stopping"
        assert completed.accepted is False
        assert completed.state == "fenced_by_stop"
        assert coordinator.can_claim(pending.generation) is False
    finally:
        connection.close()


def test_stop_retry_is_idempotent_and_new_start_uses_new_generation() -> None:
    connection, coordinator = _coordinator()
    try:
        first_stop = coordinator.stop("req-stop")
        repeated_stop = coordinator.stop("req-stop")
        assert repeated_stop == first_stop
        pending = coordinator.begin_start("req-start-2", _ready())
        completed = coordinator.complete_start("req-start-2")
        assert pending.generation > first_stop.generation
        assert completed.accepted is True
        assert completed.state == "running"
        assert coordinator.can_claim(completed.generation) is True
    finally:
        connection.close()


def test_subscription_or_ban_blocks_start_without_external_action() -> None:
    connection, coordinator = _coordinator()
    try:
        blocked = build_readiness(
            version="v2",
            scope="tenant:1",
            checks={"subscription": False, "ban": True},
            blockers=("subscription_inactive",),
        )
        result = coordinator.begin_start("req-blocked", blocked)
        assert result.accepted is False
        assert result.state == "blocked"
        assert coordinator.can_claim(result.generation) is False
    finally:
        connection.close()


def test_readiness_report_rejects_missing_scope_and_preserves_selection() -> None:
    with pytest.raises(ValueError):
        build_readiness(version="v2", scope="", checks={})
    report = _ready()
    assert report.selection == {"profiles": [1, 2], "targets": {"1": 5, "2": 7}}


def test_campaign_start_is_fenced_when_stop_wins_during_preflight(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    monkeypatch.setenv("MAX_DATA", str(tmp_path / "data"))
    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.reset_test_runtime()
    m.init_db()
    with m._conn() as connection:
        connection.execute(
            "INSERT INTO profiles (id, phone, status) VALUES (7, '+79990007777', 'active')"
        )
        connection.execute(
            "INSERT INTO groups (id, name, max_chat_id, is_active) VALUES (3, 'fixture', '77', 1)"
        )
        connection.execute(
            "INSERT INTO group_profiles (group_id, profile_id, is_enabled) VALUES (3, 7, 1)"
        )

    from app import routes_campaign
    from app.routes_campaign import CampaignCommandCoordinator, campaign_start

    coordinator = CampaignCommandCoordinator(m._conn(), scope="local")
    start_worker = AsyncMock()

    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["fixture"])
    monkeypatch.setattr(m, "_active_groups", lambda: [{"id": 3}])
    monkeypatch.setattr(m, "_has_active_profiles", lambda: True)
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)
    monkeypatch.setattr(m, "_start_worker", start_worker)

    async def stop_during_preflight() -> None:
        coordinator.stop("stop-during-preflight")

    monkeypatch.setattr(
        routes_campaign.m, "_preflight_group_proxies", stop_during_preflight, raising=False
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(campaign_start())

    assert exc_info.value.status_code == 409
    assert start_worker.await_count == 0
    assert m.get_setting("auto_run") in ("", "0")
