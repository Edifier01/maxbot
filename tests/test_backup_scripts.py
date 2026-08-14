"""Guard: volume backup/restore must use the app service, not a missing alpine service."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_backup_restore_do_not_compose_run_alpine():
    backup = (ROOT / "scripts" / "backup-volumes.sh").read_text(encoding="utf-8")
    restore = (ROOT / "scripts" / "restore-volumes.sh").read_text(encoding="utf-8")
    assert "alpine sh" not in backup
    assert "alpine sh" not in restore
    assert "docker compose run --rm -T --no-deps --entrypoint tar" in backup
    assert "app czf - -C /app/data" in backup
    assert "--entrypoint python" in restore
    assert 'tarfile.open("/backup/data.tar.gz")' in restore


def test_deploy_ssh_timeout_covers_image_build():
    deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    assert "command_timeout: 30m" in deploy
    assert "docker compose build --no-cache" not in deploy
    assert "docker compose build app" in deploy
