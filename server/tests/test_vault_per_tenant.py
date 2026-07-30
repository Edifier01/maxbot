"""P1: vault state изолирован по data-dir (tenant)."""

from __future__ import annotations

from cryptography.fernet import Fernet

from app import vault
from app.tenant import clear_context, set_context


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
