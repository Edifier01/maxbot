"""P1: vault state изолирован по data-dir (tenant)."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app import vault
from app.tenant import clear_context, set_context, tenant_scope


def test_vault_cache_per_tenant_data_dir(tmp_path):
    root = tmp_path / "root"
    root.mkdir()

    vault.clear_cache()
    key_a = Fernet.generate_key()
    key_b = Fernet.generate_key()

    d1 = root / "data" / "tenants" / "1"
    d2 = root / "data" / "tenants" / "2"

    set_context(tenant_id=1, role="user")
    vault.set_state(d1, Fernet(key_a), True)
    _, unlocked_a = vault.get_state(d1)
    assert unlocked_a

    set_context(tenant_id=2, role="user")
    _, unlocked_b = vault.get_state(d2)
    assert not unlocked_b

    vault.set_state(d2, Fernet(key_b), True)
    set_context(tenant_id=1, role="user")
    fernet_a, unlocked_a2 = vault.get_state(d1)
    assert unlocked_a2
    assert fernet_a.decrypt(Fernet(key_a).encrypt(b"probe")) == b"probe"

    clear_context()


def test_main_hot_path_resolves_per_tenant(tmp_path, monkeypatch):
    """main wrappers must not stick to a process-wide Fernet/SESSIONS."""
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)

    import main as m

    monkeypatch.setattr(m, "ROOT", tmp_path)
    (tmp_path / "data" / "tenants" / "1").mkdir(parents=True)
    (tmp_path / "data" / "tenants" / "2").mkdir(parents=True)
    vault.clear_cache()
    m.reset_test_runtime()

    with tenant_scope(tenant_id=1, role="user"):
        d1 = m._session_dir(7)
        m._ensure_vault_unlocked()
        f1 = m._get_fernet()
        assert "tenants" in d1.parts and "1" in d1.parts
        assert d1.name == "7"

    with tenant_scope(tenant_id=2, role="user"):
        d2 = m._session_dir(7)
        m._ensure_vault_unlocked()
        f2 = m._get_fernet()
        assert "tenants" in d2.parts and "2" in d2.parts
        token = f1.encrypt(b"tenant-a")
        try:
            f2.decrypt(token)
            raised = False
        except InvalidToken:
            raised = True
        assert raised, "tenant B must not decrypt with tenant A key"

    assert d1 != d2
    clear_context()
