"""Persistent recovery hold fences every automatic and manual start path."""

from __future__ import annotations

import asyncio
import importlib
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


def test_restore_hold_skips_auto_run_database_read_before_server_tenant_scope(
    tmp_path, monkeypatch
) -> None:
    hold = write_hold(tmp_path)
    monkeypatch.setenv("MAX_RECOVERY_HOLD_FILE", str(hold))
    import main as m

    monkeypatch.setattr(m, "_is_server_mode", lambda: True)
    monkeypatch.setattr(
        m,
        "_auto_run_enabled",
        lambda: (_ for _ in ()).throw(AssertionError("must not read tenant settings")),
    )
    assert asyncio.run(m._try_auto_resume()) is False


def test_restore_hold_survives_restart_without_resuming_or_resetting_budget(
    tmp_path, monkeypatch
) -> None:
    hold = write_hold(tmp_path, revision="restore-budget-fixture")
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    monkeypatch.setenv("JWT_SECRET", "fixture-jwt-secret-at-least-32-characters")
    monkeypatch.setenv("MAX_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("MAX_RECOVERY_HOLD_FILE", str(hold))

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    m.reset_test_runtime()
    m._refresh_data_paths()
    m.init_db()
    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "INSERT INTO profiles (phone, status, messages_sent_today, sent_day) "
            "VALUES (?, ?, ?, ?)",
            ("+79990018888", m.ProfileStatus.ACTIVE, 4, today),
        )
    m.set_setting("auto_run", "1")
    first_start = AsyncMock()
    monkeypatch.setattr(m, "_start_worker", first_start)
    monkeypatch.setattr(m, "_vault_ready_for_send", lambda: True)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["fixture"])
    monkeypatch.setattr(m, "_prepare_auto_resume_pool", lambda: True)
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)

    assert asyncio.run(m._try_auto_resume()) is False
    first_start.assert_not_awaited()
    with m._conn() as connection:
        assert connection.execute(
            "SELECT messages_sent_today, sent_day FROM profiles WHERE phone=?",
            ("+79990018888",),
        ).fetchone()["messages_sent_today"] == 4

    importlib.reload(cfg)
    importlib.reload(m)
    m.reset_test_runtime()
    m._refresh_data_paths()
    second_start = AsyncMock()
    monkeypatch.setattr(m, "_start_worker", second_start)
    monkeypatch.setattr(m, "_vault_ready_for_send", lambda: True)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["fixture"])
    monkeypatch.setattr(m, "_prepare_auto_resume_pool", lambda: True)
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)

    assert asyncio.run(m._try_auto_resume()) is False
    second_start.assert_not_awaited()
    assert recovery_hold.external_actions_status() == ("held", True)
    with m._conn() as connection:
        assert connection.execute(
            "SELECT messages_sent_today, sent_day FROM profiles WHERE phone=?",
            ("+79990018888",),
        ).fetchone()["messages_sent_today"] == 4


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
