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


def test_setup_unlock_lock_cycle(tmp_path):
    data_dir = tmp_path / "tenant"
    vault.clear_cache()

    st = vault.status(data_dir)
    assert st["needs_setup"] is True

    vault.setup(data_dir, "secure123")
    st = vault.status(data_dir)
    assert st["protected"] is True
    assert st["unlocked"] is True
    assert paths.app_salt_path(data_dir).exists()
    assert paths.app_vault_path(data_dir).exists()

    vault.lock(data_dir)
    assert vault.status(data_dir)["unlocked"] is False

    vault.unlock(data_dir, "secure123")
    assert vault.status(data_dir)["unlocked"] is True


def test_unlock_wrong_password(tmp_path):
    data_dir = tmp_path / "tenant"
    vault.clear_cache()
    vault.setup(data_dir, "correct-pass")
    vault.lock(data_dir)

    try:
        vault.unlock(data_dir, "wrong-pass")
        raised = False
    except ValueError as e:
        raised = True
        assert "Неверный пароль" in str(e)
    assert raised


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
