"""T09 staged legacy-vault migration keeps originals until semantic verification."""

from __future__ import annotations

import pytest

from app import paths, vault


def _legacy_fixture(tmp_path):
    data_dir = tmp_path / "tenant"
    vault.clear_cache()
    vault.setup(data_dir, "old-password")
    session_dir = vault.session_dir(data_dir, 7)
    (session_dir / "session.db").write_bytes(b"token=device-fixture;identity=stable")
    vault.encrypt_session_file(data_dir, 7)
    vault.lock(data_dir)
    return data_dir, session_dir


def test_migration_reseals_session_and_archives_legacy_material(tmp_path) -> None:
    from app.vault_migration import commit_migration, prepare_migration, verify_migration

    data_dir, session_dir = _legacy_fixture(tmp_path)
    plan = prepare_migration(data_dir, "old-password")
    assert verify_migration(plan) is True
    commit_migration(plan)

    vault.clear_cache()
    assert vault.status(data_dir)["unlocked"] is True
    vault.decrypt_session_file(data_dir, 7)
    assert (session_dir / "session.db").read_bytes() == b"token=device-fixture;identity=stable"
    assert not paths.app_salt_path(data_dir).exists()
    assert not paths.app_vault_path(data_dir).exists()
    assert list(data_dir.glob("legacy-vault-backup-*"))


def test_wrong_password_blocks_without_erasing_legacy_files(tmp_path) -> None:
    from app.vault_migration import VaultMigrationError, prepare_migration

    data_dir, session_dir = _legacy_fixture(tmp_path)
    salt = paths.app_salt_path(data_dir).read_bytes()
    encrypted = (session_dir / "session.db.enc").read_bytes()
    with pytest.raises(VaultMigrationError) as caught:
        prepare_migration(data_dir, "wrong-password")
    assert caught.value.code == "VAULT_KEY_REQUIRED"
    assert paths.app_salt_path(data_dir).read_bytes() == salt
    assert (session_dir / "session.db.enc").read_bytes() == encrypted
    assert not paths.app_key_path(data_dir).exists()

def test_corrupt_session_blocks_without_partial_commit(tmp_path) -> None:
    from app.vault_migration import VaultMigrationError, prepare_migration

    data_dir, session_dir = _legacy_fixture(tmp_path)
    (session_dir / "session.db.enc").write_bytes(b"corrupt")
    with pytest.raises(VaultMigrationError) as caught:
        prepare_migration(data_dir, "old-password")
    assert caught.value.code == "VAULT_INTEGRITY_FAILED"
    assert paths.app_salt_path(data_dir).exists()
    assert paths.app_vault_path(data_dir).exists()
    assert not paths.app_key_path(data_dir).exists()
