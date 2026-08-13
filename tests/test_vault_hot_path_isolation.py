"""FEATURE-VAULT-CI-2026: main vault/session hot path must be per-tenant data_dir.

Fails if process-global Fernet/SESSIONS leak across tenants after context switch.
Passes when encrypt/decrypt/session paths resolve per data_dir (.app_key).
"""

from __future__ import annotations

import importlib

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.tenant import tenant_scope


def test_main_vault_session_hot_path_isolated_per_tenant(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import app.config as cfg

    importlib.reload(cfg)

    import main as m

    m.reset_test_runtime()
    try:
        from app import vault

        vault.clear_cache()
    except Exception:
        pass

    monkeypatch.setattr(m, "ROOT", tmp_path)

    key1 = Fernet.generate_key()
    key2 = Fernet.generate_key()
    assert key1 != key2

    d1 = tmp_path / "data" / "tenants" / "1"
    d2 = tmp_path / "data" / "tenants" / "2"
    d1.mkdir(parents=True)
    d2.mkdir(parents=True)
    (d1 / ".app_key").write_bytes(key1)
    (d2 / ".app_key").write_bytes(key2)

    plain_a = b"tenant-A-session-bytes"
    plain_b = b"tenant-B-session-bytes-OTHER"
    profile_id = 7

    # Tenant A: unlock + encrypt via production main wrappers (do not clear _fernet after).
    with tenant_scope(tenant_id=1, role="user"):
        m._refresh_data_paths()
        m._ensure_vault_unlocked()
        sess1 = m._session_dir(profile_id)
        assert sess1.resolve() == (d1 / "sessions" / str(profile_id)).resolve()
        (sess1 / "session.db").write_bytes(plain_a)
        m._encrypt_session(profile_id)
        enc1 = sess1 / "session.db.enc"
        assert enc1.is_file()
        assert not (sess1 / "session.db").exists()
        assert Fernet(key1).decrypt(enc1.read_bytes()) == plain_a
        with pytest.raises(InvalidToken):
            Fernet(key2).decrypt(enc1.read_bytes())

    # Tenant B: switch context without reset_test_runtime — sticky global Fernet must not win.
    with tenant_scope(tenant_id=2, role="user"):
        m._refresh_data_paths()
        m._ensure_vault_unlocked()
        sess2 = m._session_dir(profile_id)
        assert sess2.resolve() == (d2 / "sessions" / str(profile_id)).resolve()
        (sess2 / "session.db").write_bytes(plain_b)
        m._encrypt_session(profile_id)
        enc2 = sess2 / "session.db.enc"
        assert enc2.is_file()
        assert not (sess2 / "session.db").exists()
        # Correct end state: ciphertext bound to tenant B key, not A's leftover Fernet.
        assert Fernet(key2).decrypt(enc2.read_bytes()) == plain_b
        with pytest.raises(InvalidToken):
            Fernet(key1).decrypt(enc2.read_bytes())

    # Round-trip decrypt under each context; no cross-tenant plaintext bleed into the other dir.
    with tenant_scope(tenant_id=1, role="user"):
        m._refresh_data_paths()
        m._ensure_vault_unlocked()
        m._decrypt_session(profile_id)
        assert (d1 / "sessions" / str(profile_id) / "session.db").read_bytes() == plain_a
        assert not (d2 / "sessions" / str(profile_id) / "session.db").exists()

    with tenant_scope(tenant_id=2, role="user"):
        m._refresh_data_paths()
        m._ensure_vault_unlocked()
        m._decrypt_session(profile_id)
        assert (d2 / "sessions" / str(profile_id) / "session.db").read_bytes() == plain_b
        assert (d1 / "sessions" / str(profile_id) / "session.db").read_bytes() == plain_a
