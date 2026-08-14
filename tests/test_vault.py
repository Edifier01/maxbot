"""Unit tests for app.vault."""

from __future__ import annotations

from cryptography.fernet import Fernet

from app import paths, vault


def test_derive_fernet_roundtrip():
    salt = b"0123456789abcdef"
    f1 = vault.derive_fernet("secret-pass", salt)
    f2 = vault.derive_fernet("secret-pass", salt)
    token = f1.encrypt(b"payload")
    assert f2.decrypt(token) == b"payload"


def test_auto_unlock_fresh_dir(tmp_path):
    data_dir = tmp_path / "tenant"
    vault.clear_cache()

    st = vault.status(data_dir)
    assert st["unlocked"] is True
    assert st["needs_setup"] is False
    assert paths.app_key_path(data_dir).exists()


def test_auto_unlock_drops_password_vault(tmp_path):
    data_dir = tmp_path / "tenant"
    vault.clear_cache()
    vault.setup(data_dir, "secure123")
    vault.lock(data_dir)
    assert vault.get_state(data_dir)[1] is False

    st = vault.status(data_dir)
    assert st["unlocked"] is True
    assert not paths.app_salt_path(data_dir).exists()
    assert paths.app_key_path(data_dir).exists()


def test_setup_api_before_status(tmp_path):
    """Legacy setup API still works if called before status()."""
    data_dir = tmp_path / "tenant"
    vault.clear_cache()
    vault.setup(data_dir, "secure123")
    assert paths.app_salt_path(data_dir).exists()
    assert vault.get_state(data_dir)[1] is True


def test_per_tenant_state_isolation(tmp_path):
    vault.clear_cache()
    d1 = tmp_path / "t1"
    d2 = tmp_path / "t2"
    key_a = Fernet.generate_key()
    key_b = Fernet.generate_key()

    vault.set_state(d1, Fernet(key_a), True)
    assert vault.get_state(d1)[1]
    assert not vault.get_state(d2)[1]

    vault.set_state(d2, Fernet(key_b), True)
    fernet_a, unlocked_a = vault.get_state(d1)
    assert unlocked_a
    assert fernet_a.decrypt(Fernet(key_a).encrypt(b"x")) == b"x"


def test_decrypt_invalid_token_keeps_enc(tmp_path):
    import pytest

    data_dir = tmp_path / "tenant"
    vault.clear_cache()
    vault.ensure_vault_unlocked(data_dir)
    d = vault.session_dir(data_dir, 3)
    enc = d / "session.db.enc"
    enc.write_bytes(b"not-a-fernet-token")
    with pytest.raises(RuntimeError, match="расшифровать"):
        vault.decrypt_session_file(data_dir, 3)
    assert enc.is_file()
    assert not (d / "session.db").exists()


def test_encrypt_skips_empty_db_when_enc_exists(tmp_path):
    data_dir = tmp_path / "tenant"
    vault.clear_cache()
    vault.ensure_vault_unlocked(data_dir)
    d = vault.session_dir(data_dir, 4)
    db, enc = d / "session.db", d / "session.db.enc"
    good = b"keep-me-encrypted"
    enc.write_bytes(vault.get_fernet(data_dir).encrypt(good))
    db.write_bytes(b"not-a-sqlite-session")
    vault.encrypt_session_file(data_dir, 4)
    assert not db.exists()
    assert vault.get_fernet(data_dir).decrypt(enc.read_bytes()) == good
