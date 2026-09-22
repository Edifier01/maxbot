"""Persistent recovery hold fences every automatic and manual start path."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import recovery_hold
from app import routes_campaign
from app.platform_policy import AuthorizationRecord, MaxAction, MaxTransport
from app.services.max_gateway import GuardedMaxGateway


def write_hold(tmp_path: Path, *, revision: str = "restore-20260920-120000") -> Path:
    path = tmp_path / "recovery-hold.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "revision": revision,
                "reason": "restore",
                "created_at": "2026-09-20T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_restore_hold_fences_auto_resume(tmp_path, monkeypatch) -> None:
    async def run() -> None:
        hold = write_hold(tmp_path)
        monkeypatch.setenv("MAX_RECOVERY_HOLD_FILE", str(hold))
        start = AsyncMock()

        import main as m

        monkeypatch.setattr(m, "_auto_run_enabled", lambda: True)
        monkeypatch.setattr(m, "_start_worker", start)
        monkeypatch.setattr(m, "_vault_ready_for_send", lambda: True)
        monkeypatch.setattr(m, "load_message_pool", lambda: ["fixture"])
        monkeypatch.setattr(m, "_prepare_auto_resume_pool", lambda: True)
        monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)

        assert await m._try_auto_resume() is False

        start.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize(
    "entrypoint",
    [routes_campaign.campaign_start, routes_campaign.campaign_test],
)
def test_manual_entrypoints_check_hold_before_preflight(entrypoint, monkeypatch) -> None:
    check = Mock(
        side_effect=recovery_hold.RecoveryHoldActive("recovery_hold_active")
    )
    monkeypatch.setattr(recovery_hold, "require_external_actions_released", check)

    with pytest.raises(recovery_hold.RecoveryHoldActive):
        asyncio.run(entrypoint())

    check.assert_called_once()


def test_gateway_hold_blocks_before_adapter_call(tmp_path, monkeypatch) -> None:
    hold = write_hold(tmp_path)
    monkeypatch.setenv("MAX_RECOVERY_HOLD_FILE", str(hold))
    now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    calls: list[str] = []

    class Adapter:
        async def connect(self):
            calls.append("connect")
            return SimpleNamespace()

    gateway = GuardedMaxGateway(
        adapter=Adapter(),
        record=AuthorizationRecord(
            schema_version=1,
            reference="fixture",
            transport=MaxTransport.AUTHORIZED_USER_SESSION,
            allowed_actions=frozenset({MaxAction.CONNECT}),
            valid_from=now - timedelta(minutes=1),
            valid_until=now + timedelta(minutes=1),
        ),
        clock=lambda: now,
    )

    with pytest.raises(recovery_hold.RecoveryHoldActive):
        asyncio.run(gateway.connect())

    assert calls == []


def test_release_command_requires_exact_revision_and_records_before_delete(tmp_path) -> None:
    hold = write_hold(tmp_path, revision="restore-fixture-1")
    env = os.environ.copy()
    env["MAX_RECOVERY_HOLD_FILE"] = str(hold)
    command = [
        sys.executable,
        "scripts/release-recovery-hold.py",
        "--expected-revision",
        "wrong-revision",
        "--authorization-reference",
        "OPS-FIXTURE-1",
    ]
    failed = subprocess.run(command, check=False, capture_output=True, text=True, env=env)
    assert failed.returncode == 1
    assert hold.is_file()

    command[command.index("wrong-revision")] = "restore-fixture-1"
    released = subprocess.run(command, check=False, capture_output=True, text=True, env=env)
    assert released.returncode == 0
    assert not hold.exists()
    evidence = tmp_path / "recovery-release.jsonl"
    record = json.loads(evidence.read_text(encoding="utf-8").strip())
    assert record["hold_revision"] == "restore-fixture-1"
    assert record["authorization_reference"] == "OPS-FIXTURE-1"
