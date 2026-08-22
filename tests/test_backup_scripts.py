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
    extract_at = restore.index("extractall")
    assert ".incoming" in restore[:extract_at]
    assert "for child in list(root.iterdir())" not in restore[:extract_at]
    assert restore.index("--entrypoint python") < restore.index("pg_restore")
    assert 'filter="data"' in restore
    assert "os.chown(incoming, 10001, 10001)" in restore


def test_backup_verifies_archive_integrity():
    backup = (ROOT / "scripts" / "backup-volumes.sh").read_text(encoding="utf-8")
    assert '[[ ! -s "$DEST/pg.dump" ]]' in backup
    assert "PGDMP" in backup
    assert 'gzip -t "$DEST/data.tar.gz"' in backup
    assert 'tar -tzf "$DEST/data.tar.gz"' in backup
    assert "no tar members" in backup
    assert backup.index("gzip -t") < backup.index('echo "Done:')
    assert backup.index("no tar members") < backup.index('echo "Done:')


def test_backup_umask_and_wal_checkpoint():
    backup = (ROOT / "scripts" / "backup-volumes.sh").read_text(encoding="utf-8")
    assert "umask 077" in backup
    assert backup.index("umask 077") < backup.index("mkdir")
    assert 'chmod 700 "$DEST"' in backup
    assert backup.index("mkdir") < backup.index('chmod 700 "$DEST"')
    assert "PRAGMA wal_checkpoint(TRUNCATE)" in backup
    assert backup.index("wal_checkpoint") < backup.index("data.tar.gz")
    assert "docker compose stop celery-worker app" in backup
    assert "trap restart_after_backup EXIT INT TERM" in backup
    assert "docker compose start" in backup
    assert backup.index("docker compose stop celery-worker app") < backup.index("pg_dump")


def test_restore_defers_outgoing_rmtree_until_pg_ok():
    restore = (ROOT / "scripts" / "restore-volumes.sh").read_text(encoding="utf-8")
    assert "--exit-on-error" in restore
    pg_at = restore.index("pg_restore")
    assert "shutil.rmtree(outgoing)" not in restore[:pg_at]
    assert restore.index("shutil.rmtree(outgoing)") > pg_at
    assert "rolling data volume back" in restore
    assert "leftover .outgoing-restore" in restore
    assert '"${1:-}" == "--yes"' in restore
    assert 'if [[ "$ASSUME_YES" != "1" ]]' in restore


def test_dr_smoke_exercises_backup_then_restore():
    smoke = (ROOT / "scripts" / "dr-smoke.sh").read_text(encoding="utf-8")
    assert "backup-volumes.sh" in smoke
    assert "restore-volumes.sh --yes" in smoke
    assert "SELECT value FROM dr_smoke" in smoke
    assert "/app/data/dr-smoke/value" in smoke


def test_deploy_ssh_timeout_covers_image_build():
    deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    assert "command_timeout: 30m" in deploy
    assert "docker compose build --no-cache" not in deploy
    assert "docker compose build app" in deploy
    assert "reset --hard origin/main" not in deploy
    assert "reset --hard origin/master" not in deploy
    assert "workflow_run" not in deploy
    assert "workflow_dispatch:" in deploy
    assert "github.sha" in deploy
    assert 'ref: ${{ github.sha }}' in deploy
    assert "checkout --force" in deploy
    assert "--profile celery" in deploy
    assert "up -d postgres" in deploy
    assert "No postgres volume/data" in deploy


def test_deploy_sh_mirrors_backup_gate_and_celery_profile():
    deploy_sh = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    assert "up -d postgres" in deploy_sh
    assert "No postgres volume/data" in deploy_sh
    assert "--profile celery" in deploy_sh
    assert "postgres not running" not in deploy_sh


def test_ops_docs_pg_restore_rollback():
    ops = (ROOT / "docs" / "PRODUCTION-OPS.md").read_text(encoding="utf-8")
    assert "rolls the data volume back" in ops or "rolls data volume back" in ops
    assert "--exit-on-error" in ops
    assert "trigger-only" in ops
    assert "horizontal scale" not in ops.lower()


def test_ci_actions_images_and_permissions_are_immutable():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    for workflow in (ci, deploy):
        assert "permissions:\n  contents: read" in workflow
        assert "actions/checkout@v" not in workflow
        assert "actions/setup-python@v" not in workflow
    assert "appleboy/ssh-action@v" not in deploy
    assert "environment: production" in deploy
    assert "postgres:16-alpine@sha256:" in ci
    assert "dependency-audit:" in ci
    assert "pip-audit -r requirements.lock" in ci
    assert "pip-audit -r requirements-server.lock" in ci


def test_compose_has_runtime_resource_limits():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert compose.count("mem_limit:") >= 5
    assert compose.count("cpus:") >= 5
    assert compose.count("pids_limit:") >= 5
