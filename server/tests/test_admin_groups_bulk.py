"""Admin bulk group activate/deactivate."""

from __future__ import annotations

import importlib

import pytest

from app.tenant import tenant_scope


def _setup_tenant_db(main_mod, tenant_id: int, groups: list[tuple[str, int]]) -> None:
    from app.tenant_init import ensure_tenant_data

    ensure_tenant_data(main_mod.ROOT, tenant_id)
    with tenant_scope(tenant_id=tenant_id, role="user"):
        if not main_mod._db_path().exists():
            main_mod.init_db()
        with main_mod._conn() as c:
            for name, is_active in groups:
                c.execute(
                    "INSERT INTO groups (name, invite_link, is_active) VALUES (?, ?, ?)",
                    (name, "https://example.com/g", is_active),
                )


def test_bulk_set_groups_active(monkeypatch, tmp_path):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()

    _setup_tenant_db(m, 1, [("G1", 0), ("G2", 1)])
    _setup_tenant_db(m, 2, [("H1", 1)])

    monkeypatch.setattr(
        "app.routes_admin.db_pg.list_tenants_with_users",
        lambda: [{"tenant_id": 1}, {"tenant_id": 2}, {"tenant_id": 99}],
    )
    monkeypatch.setattr(m, "append_log", lambda msg: None)

    from app.routes_admin import _bulk_set_groups_active

    out = _bulk_set_groups_active(1)
    assert out["ok"] is True
    assert out["tenants_processed"] == 2
    assert out["groups_updated"] == 3
    assert len(out["skipped"]) == 1
    assert out["skipped"][0]["tenant_id"] == 99

    with tenant_scope(tenant_id=1, role="user"):
        rows = m._conn().execute("SELECT is_active FROM groups ORDER BY id").fetchall()
    assert [r["is_active"] for r in rows] == [1, 1]

    out_off = _bulk_set_groups_active(0)
    assert out_off["groups_updated"] == 3
    with tenant_scope(tenant_id=2, role="user"):
        rows = m._conn().execute("SELECT is_active FROM groups").fetchall()
    assert all(r["is_active"] == 0 for r in rows)


def test_bulk_groups_requires_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-min-32-characters-long")

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()

    from starlette.testclient import TestClient

    with TestClient(m.app) as client:
        r = client.post("/api/admin/groups/activate-all")
    assert r.status_code == 401
