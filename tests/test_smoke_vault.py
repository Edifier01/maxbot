"""Smoke: vault setup / unlock / lock / status."""

from __future__ import annotations

from tests.conftest import setup_vault


def test_vault_setup_unlock_lock_cycle(client):
    st = client.get("/api/vault/status").json()
    assert st["needs_setup"] is True

    setup_vault(client, "secure123")

    st = client.get("/api/vault/status").json()
    assert st["protected"] is True
    assert st["unlocked"] is True

    r = client.post("/api/vault/lock")
    assert r.status_code == 200
    st = r.json()
    assert st["unlocked"] is False

    r = client.post("/api/vault/unlock", json={"password": "secure123"})
    assert r.status_code == 200
    assert r.json()["unlocked"] is True


def test_vault_wrong_password(client):
    setup_vault(client, "correct-pass")
    client.post("/api/vault/lock")

    r = client.post("/api/vault/unlock", json={"password": "wrong-pass"})
    assert r.status_code == 401
