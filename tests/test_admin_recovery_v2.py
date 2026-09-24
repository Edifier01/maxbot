"""A40: explicit administrator recovery and persistent session invalidation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io


def test_auth_epoch_invalidates_old_tokens_and_accepts_new_tokens(tmp_path, monkeypatch) -> None:
    epoch_file = tmp_path / "auth-epoch.json"
    monkeypatch.setenv("MAX_AUTH_EPOCH_FILE", str(epoch_file))

    from app import auth_epoch

    old_payload = {
        "iat": datetime.now(UTC) - timedelta(minutes=1),
        "sub": "7",
    }
    assert auth_epoch.token_is_current(old_payload) is True
    written = auth_epoch.write_epoch("OPS-RECOVERY-1")
    assert written > 0
    assert auth_epoch.token_is_current(old_payload) is False
    assert auth_epoch.token_is_current({"iat": written + 2, "sub": "7"}) is True
    assert auth_epoch.token_is_current({"ae": written, "iat": 1, "sub": "7"}) is True
    assert auth_epoch.token_is_current({"ae": written - 1, "iat": written + 2, "sub": "7"}) is False


def test_malformed_auth_epoch_fails_closed_for_session_validation(tmp_path, monkeypatch) -> None:
    epoch_file = tmp_path / "auth-epoch.json"
    epoch_file.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("MAX_AUTH_EPOCH_FILE", str(epoch_file))

    from app import auth

    assert auth.validate_token_session({"iat": 1, "sub": "7"}) == (
        "Сессия требует повторной авторизации"
    )


def test_recovery_command_requires_reference_and_hashes_stdin_password(monkeypatch) -> None:
    from app import admin_recovery

    monkeypatch.setattr(admin_recovery, "is_server_mode", lambda: True)
    monkeypatch.setattr(admin_recovery, "require_jwt_secret", lambda: "fixture")
    monkeypatch.setattr(admin_recovery, "require_database_url", lambda: "fixture")
    monkeypatch.setattr(
        admin_recovery.db_pg,
        "get_admin_by_email",
        lambda email: {"id": 7, "email": email, "role": "admin"},
    )
    monkeypatch.setattr(admin_recovery.auth, "hash_password", lambda value: f"hash:{value}")
    epoch_calls: list[str] = []
    monkeypatch.setattr(
        admin_recovery.auth_epoch,
        "write_epoch",
        lambda reference: epoch_calls.append(reference) or 123.0,
    )
    updated: list[tuple[str, str]] = []
    monkeypatch.setattr(
        admin_recovery.db_pg,
        "update_admin_password",
        lambda email, password_hash: updated.append((email, password_hash)) or 7,
    )
    monkeypatch.setattr(admin_recovery.sys, "stdin", io.StringIO("NewPass123!\n"))

    assert admin_recovery.main(
        [
            "--email",
            "ADMIN@example.com",
            "--authorization-reference",
            "OPS-RECOVERY-2",
            "--password-stdin",
        ]
    ) == 0
    assert epoch_calls == ["OPS-RECOVERY-2"]
    assert updated == [("admin@example.com", "hash:NewPass123!")]


def test_bootstrap_prepares_home_and_ssh_authorization_before_clone() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "scripts/bootstrap-vps.sh").read_text(
        encoding="utf-8"
    )
    assert 'DEPLOY_HOME="$(getent passwd "$DEPLOY_USER"' in source
    assert "run_as_deploy()" in source
    assert source.index("git ls-remote") < source.index("git clone")
    assert 'KEY_DIR="$DEPLOY_HOME/.ssh"' in source
    assert 'KEY_DIR="/home/$DEPLOY_USER/.ssh"' not in source
