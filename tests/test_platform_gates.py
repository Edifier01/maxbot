"""Deployment and readiness contracts for the platform authorization gate."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from app import recovery_hold


ROOT = Path(__file__).resolve().parents[1]


def _record(path: Path, *, actions: list[str] | None = None, expired: bool = False) -> None:
    now = datetime.now(UTC)
    path.write_text(json.dumps({
        "schema_version": 1,
        "reference": "fixture-permission",
        "transport": "authorized_user_session",
        "allowed_actions": actions if actions is not None else ["send"],
        "valid_from": (now - timedelta(days=2)).isoformat(),
        "valid_until": (now - timedelta(days=1) if expired else now + timedelta(days=1)).isoformat(),
    }), encoding="utf-8")


def test_ssh_deploy_passes_candidate_sha_to_remote_action() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8"))
    deploy = workflow["jobs"]["deploy"]
    action = next(step for step in deploy["steps"] if step.get("name") == "Deploy via SSH")
    assert deploy["env"]["CANDIDATE_SHA"]
    assert "CANDIDATE_SHA" in action["with"]["envs"].split(",")


def test_compose_app_and_worker_receive_read_only_authorization_record() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for name in ("app", "celery-worker"):
        service = compose["services"][name]
        path = service["environment"]["MAX_PLATFORM_AUTHORIZATION_FILE"]
        assert path == "/app/authorization/platform-authorization.json"
        assert any(volume.endswith(":/app/authorization:ro") for volume in service["volumes"])


def test_image_contains_release_command_and_writable_control_directory() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY --chown=10001:10001 scripts/release-recovery-hold.py ./scripts/" in dockerfile
    assert "mkdir -p /app/data /app/control" in dockerfile


def test_external_action_status_requires_valid_send_authorization(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("MAX_RECOVERY_HOLD_FILE", raising=False)
    monkeypatch.delenv("MAX_PLATFORM_AUTHORIZATION_FILE", raising=False)
    assert recovery_hold.external_actions_status() != ("authorized", False)

    record = tmp_path / "platform-authorization.json"
    monkeypatch.setenv("MAX_PLATFORM_AUTHORIZATION_FILE", str(record))
    _record(record, expired=True)
    assert recovery_hold.external_actions_status() != ("authorized", False)
    _record(record, actions=["connect"])
    assert recovery_hold.external_actions_status() != ("authorized", False)
    _record(record)
    assert recovery_hold.external_actions_status() == ("authorized", False)
