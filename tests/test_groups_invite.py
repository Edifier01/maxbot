"""Groups API — invite_link required."""

from __future__ import annotations

import importlib


def _setup_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.init_db()
    return m


def test_create_group_requires_invite_link(tmp_path, monkeypatch):
    m = _setup_db(tmp_path, monkeypatch)
    from starlette.testclient import TestClient

    with TestClient(m.app) as client:
        r = client.post("/api/groups", json={"name": "G1", "invite_link": ""})
        assert r.status_code == 400
        assert "ссылк" in r.json()["detail"].lower()

        ok = client.post(
            "/api/groups",
            json={"name": "G1", "invite_link": "https://max.ru/join/abc"},
        )
        assert ok.status_code == 200
        gid = ok.json()["id"]

        bad_patch = client.patch(f"/api/groups/{gid}", json={"invite_link": ""})
        assert bad_patch.status_code == 400
