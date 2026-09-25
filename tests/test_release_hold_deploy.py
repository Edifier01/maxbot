"""Deployment starts behind an external-action hold until an operator releases it."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CREATE_HOLD = ROOT / "scripts" / "create-recovery-hold.py"


def _run_create_hold(path: Path, revision: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "MAX_TEST": "1",
            "MAX_SERVER_MODE": "1",
            "MAX_RECOVERY_HOLD_FILE": str(path),
        }
    )
    return subprocess.run(
        [sys.executable, str(CREATE_HOLD), "--revision", revision, "--reason", "deploy"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


class TestCreateHoldIdempotency(unittest.TestCase):
    def test_existing_valid_hold_is_preserved_and_deploy_can_continue(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recovery-hold.json"
            created = _run_create_hold(path, "deploy-" + "a" * 40)
            self.assertEqual(created.returncode, 0, created.stderr)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["revision"], "deploy-" + "a" * 40)
            self.assertEqual(payload["reason"], "deploy")
            original = path.read_bytes()

            second = _run_create_hold(path, "deploy-" + "b" * 40)

            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("deploy-" + "a" * 40, second.stdout)
            self.assertEqual(path.read_bytes(), original)

    def test_existing_invalid_hold_still_stops_deploy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recovery-hold.json"
            path.write_text("{invalid", encoding="utf-8")

            result = _run_create_hold(path, "deploy-" + "b" * 40)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_text(encoding="utf-8"), "{invalid")


def test_create_hold_rejects_invalid_revision_without_creating_file(tmp_path: Path):
    path = tmp_path / "recovery-hold.json"

    result = _run_create_hold(path, "invalid\nrevision")

    assert result.returncode != 0
    assert not path.exists()


def test_all_deploy_entrypoints_create_hold_before_backup():
    local_deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    remote_deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )
    assert local_deploy.index("set-recovery-hold.sh") < local_deploy.index(
        "backup-volumes.sh"
    )
    assert "bash scripts/deploy.sh" in remote_deploy
