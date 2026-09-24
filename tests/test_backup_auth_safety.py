"""Disposable backup/restore auth-state fixtures; never touch Docker volumes."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_backup_refuses_plaintext_session_tree_and_archive(tmp_path):
    from app import backup_guard

    data = tmp_path / "data"
    session = data / "tenants" / "2" / "sessions" / "9" / "session.db"
    session.parent.mkdir(parents=True)
    session.write_bytes(b"fixture plaintext credential")
    with pytest.raises(backup_guard.UnsafeBackup, match="session.db"):
        backup_guard.check_data_tree(data)

    archive_path = tmp_path / "data.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(session, arcname="./tenants/2/sessions/9/session.db")
    with pytest.raises(backup_guard.UnsafeBackup, match="session.db"):
        backup_guard.check_data_archive(archive_path)

    session.unlink()
    backup_guard.check_data_tree(data)
    archive_path.unlink()
    with tarfile.open(archive_path, "w:gz") as archive:
        blob = b"encrypted fixture"
        info = tarfile.TarInfo("./tenants/2/sessions/9/session.db.enc")
        info.size = len(blob)
        archive.addfile(info, io.BytesIO(blob))
    backup_guard.check_data_archive(archive_path)


def test_cross_host_restore_rotates_epoch_and_never_copies_recovery_hold(tmp_path, monkeypatch):
    from app import auth_epoch, backup_guard

    source_control = tmp_path / "source-control"
    source_control.mkdir()
    source_epoch = source_control / "auth-epoch.json"
    monkeypatch.setenv("MAX_AUTH_EPOCH_FILE", str(source_epoch))
    old_token = {"sub": "7", "iat": 1, "ae": 0.0}
    recovered_epoch = auth_epoch.write_epoch("fixture-admin-recovery")
    token_after_recovery = {"sub": "7", "iat": recovered_epoch + 1, "ae": recovered_epoch}
    (source_control / "recovery-hold.json").write_text("fixture hold", encoding="utf-8")

    snapshot = tmp_path / "auth-state.json"
    backup_guard.export_auth_state(snapshot)
    assert json.loads(snapshot.read_text(encoding="utf-8"))["epoch"] == recovered_epoch
    assert "recovery-hold" not in snapshot.read_text(encoding="utf-8")

    target_control = tmp_path / "target-control"
    target_epoch = target_control / "auth-epoch.json"
    monkeypatch.setenv("MAX_AUTH_EPOCH_FILE", str(target_epoch))
    assert auth_epoch.token_is_current(old_token)
    assert auth_epoch.token_is_current(token_after_recovery)

    restored_epoch = backup_guard.rotate_auth_after_restore(snapshot, "fixture-restore")
    assert restored_epoch > recovered_epoch
    assert not auth_epoch.token_is_current(old_token)
    assert not auth_epoch.token_is_current(token_after_recovery)
    assert not (target_control / "recovery-hold.json").exists()


def test_restore_with_missing_legacy_snapshot_still_revokes_old_jwt(tmp_path, monkeypatch):
    from app import auth_epoch, backup_guard

    monkeypatch.setenv("MAX_AUTH_EPOCH_FILE", str(tmp_path / "auth-epoch.json"))
    legacy_token = {"sub": "7", "iat": 1, "ae": 0.0}

    backup_guard.rotate_auth_after_restore(tmp_path / "missing.json", "fixture-legacy-restore")

    assert not auth_epoch.token_is_current(legacy_token)


def test_malformed_auth_snapshot_fails_before_epoch_change(tmp_path, monkeypatch):
    from app import auth_epoch, backup_guard

    target = tmp_path / "auth-epoch.json"
    monkeypatch.setenv("MAX_AUTH_EPOCH_FILE", str(target))
    snapshot = tmp_path / "auth-state.json"
    snapshot.write_text('{"schema_version":1,"epoch":"bad"}', encoding="utf-8")

    with pytest.raises(backup_guard.UnsafeBackup):
        backup_guard.rotate_auth_after_restore(snapshot, "fixture-restore")
    assert not target.exists()


def test_restore_preflight_rejects_bad_auth_snapshot_before_mutation(tmp_path, monkeypatch):
    from app import auth_epoch, backup_guard

    control = tmp_path / "control"
    control.mkdir()
    target = control / "auth-epoch.json"
    monkeypatch.setenv("MAX_AUTH_EPOCH_FILE", str(target))
    snapshot = tmp_path / "auth-state.json"
    snapshot.write_text('{"schema_version":1,"epoch":"bad"}', encoding="utf-8")

    with pytest.raises(backup_guard.UnsafeBackup, match="invalid backup auth state"):
        backup_guard.preflight_restore(snapshot)

    assert not target.exists()
    assert list(control.iterdir()) == []


def test_restore_preflight_checks_control_writeability_without_rotating_epoch(
    tmp_path, monkeypatch
):
    from app import auth_epoch, backup_guard

    control = tmp_path / "control"
    control.mkdir()
    target = control / "auth-epoch.json"
    monkeypatch.setenv("MAX_AUTH_EPOCH_FILE", str(target))
    snapshot = tmp_path / "auth-state.json"
    snapshot.write_text('{"schema_version":1,"epoch":12}', encoding="utf-8")

    backup_guard.preflight_restore(snapshot)

    assert auth_epoch.current_epoch() == 0.0
    assert list(control.iterdir()) == []


def test_volume_backup_wires_plaintext_gate_and_auth_snapshot_before_success():
    script = (ROOT / "scripts" / "backup-volumes.sh").read_text(encoding="utf-8")
    assert script.index("app.backup_guard check-tree") < script.index("app czf - -C /app/data")
    assert script.index("app.backup_guard export-auth") < script.index('echo "Done:')
    assert script.index("session[.]db") > script.index('tar -tzf "$DEST/data.tar.gz"')
    assert script.index("session[.]db") < script.index('echo "Done:')
    assert script.index("app.backup_guard check-archive") > script.index("app czf - -C /app/data")
    assert script.index("app.backup_guard check-archive") < script.index('echo "Done:')
    assert script.rindex('rm -f "$DEST/data.tar.gz"') > script.index("session[.]db")
    assert "archive_started=1" in script
    assert "if ((archive_started)) && (( ! backup_complete )); then" in script


def test_volume_restore_rotates_auth_before_restarting_services():
    script = (ROOT / "scripts" / "restore-volumes.sh").read_text(encoding="utf-8")
    assert script.index("app.backup_guard preflight-restore") < script.index("docker compose stop app celery-worker")
    assert script.index("app.backup_guard rotate-auth") > script.index("if docker compose exec -T postgres pg_restore")
    assert script.index("app.backup_guard rotate-auth") < script.index("docker compose up -d")
    assert script.index("app.backup_guard rotate-auth") < script.index("shutil.rmtree(outgoing)")
    assert script.index("session[.]db") < script.index("Восстановление data volume")
