"""paths + vault_store modules."""

from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet

from app import paths, vault_store


def test_paths_helpers():
    d = Path("/tmp/tenant-1")
    assert paths.db_path(d) == d / "app.db"
    assert paths.sessions_root(d) == d / "sessions"


def test_vault_store_per_key():
    vault_store.clear_all()
    k1 = vault_store.store_key(Path("/a"))
    k2 = vault_store.store_key(Path("/b"))
    vault_store.set_state(k1, Fernet(Fernet.generate_key()), True)
    _, u2 = vault_store.get(k2)
    assert not u2
    _, u1 = vault_store.get(k1)
    assert u1
