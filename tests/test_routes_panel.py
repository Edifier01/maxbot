"""Routes are registered via register_panel."""

from __future__ import annotations

import importlib


def test_panel_routes_registered():
    import main as m

    importlib.reload(m)
    paths = set(m.app.openapi().get("paths", {}))
    for path in (
        "/api/health",
        "/api/vault/status",
        "/api/campaign/start",
        "/api/profiles",
        "/api/groups",
        "/api/messages",
        "/api/settings",
        "/api/dashboard",
        "/",
    ):
        assert path in paths, path


def test_messages_upload(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)

    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.init_db()

    from starlette.testclient import TestClient

    with TestClient(m.app) as client:
        r = client.post(
            "/api/messages/upload",
            files={"file": ("t.txt", b"hello\nworld\n", "text/plain")},
        )
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 2


def test_list_backups(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)

    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.init_db()
    backups = m._backups_dir()
    backups.mkdir(parents=True, exist_ok=True)
    (backups / "app-test.db").write_bytes(b"x")

    from starlette.testclient import TestClient

    with TestClient(m.app) as client:
        r = client.get("/api/backups")
    assert r.status_code == 200, r.text
    names = [item["file"] for item in r.json()["items"]]
    assert "app-test.db" in names


def test_backup_database_uses_tenant_backups_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "1")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)

    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.reset_test_runtime()

    from app.tenant import tenant_scope

    with tenant_scope(tenant_id=42, role="user"):
        m.init_db()
        dest = m.backup_database()

    assert dest is not None
    tenant_backups = tmp_path / "data" / "tenants" / "42" / "backups"
    assert dest.parent == tenant_backups
    assert dest.is_file()
    global_backups = tmp_path / "data" / "backups"
    assert not list(global_backups.glob("app-*.db")) if global_backups.exists() else True

