"""Smoke: GET /api/health."""

from __future__ import annotations


def test_health_ok(client, main_module):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["db_ok"] is True
    assert body["ok"] is True
    assert body["version"] == main_module.APP_VERSION
    assert body["db_backend"] == "sqlite"
    assert "vault" in body
