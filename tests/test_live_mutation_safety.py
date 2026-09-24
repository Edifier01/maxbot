"""Campaign inputs stay immutable while a worker can consume them."""

from __future__ import annotations

import asyncio
import importlib

import pytest
from fastapi import HTTPException


def _setup_local(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    m.reset_test_runtime()
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.init_db()
    return m


def test_worker_idle_guard_rejects_running_worker(tmp_path, monkeypatch):
    m = _setup_local(tmp_path, monkeypatch)

    class BusyTask:
        @staticmethod
        def done():
            return False

    m.REGISTRY.worker().worker_task = BusyTask()
    with pytest.raises(HTTPException) as exc:
        m._require_worker_idle()
    assert exc.value.status_code == 409


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/api/groups", {"name": "g", "invite_link": "https://max.ru/join/x"}),
        ("patch", "/api/groups/1", {"name": "g2"}),
        ("post", "/api/groups/1/profiles", {"phone": "+79000000001"}),
        (
            "post",
            "/api/groups/1/profiles/bulk",
            {"profiles": [{"phone": "+79000000001"}]},
        ),
        ("delete", "/api/groups/1", None),
        ("delete", "/api/groups/1/profiles/1", None),
        ("patch", "/api/profiles/1", {"label": "new"}),
        ("post", "/api/profiles/1/login/reset", None),
        ("post", "/api/profiles/1/login", None),
        ("post", "/api/profiles/1/sms", {"code": "1234"}),
        ("post", "/api/profiles/1/password", {"code": "secret"}),
        ("patch", "/api/profiles/1/disable", None),
    ],
)
def test_mutating_routes_share_busy_guard(tmp_path, monkeypatch, method, path, body):
    m = _setup_local(tmp_path, monkeypatch)
    from starlette.testclient import TestClient

    def reject():
        raise HTTPException(409, "Остановите рассылку")

    monkeypatch.setattr(m, "_require_worker_idle", reject, raising=False)
    with TestClient(m.app) as client:
        response = client.request(method, path, json=body)
    assert response.status_code == 409


def test_formatted_duplicate_phone_is_one_profile(tmp_path, monkeypatch):
    m = _setup_local(tmp_path, monkeypatch)
    from starlette.testclient import TestClient

    with TestClient(m.app) as client:
        group_id = client.post(
            "/api/groups",
            json={"name": "g", "invite_link": "https://max.ru/join/x"},
        ).json()["id"]
        first = client.post(
            f"/api/groups/{group_id}/profiles", json={"phone": "8 (938) 002-15-75"}
        )
        duplicate = client.post(
            f"/api/groups/{group_id}/profiles", json={"phone": "+7 938 002 15 75"}
        )

    assert first.status_code == 200
    assert first.json()["phone"] == "+79380021575"
    assert duplicate.status_code == 400
    with m._conn() as c:
        assert c.execute("SELECT COUNT(*) n FROM profiles").fetchone()["n"] == 1


def test_orphan_profile_is_retained_when_runtime_cleanup_fails(tmp_path, monkeypatch):
    m = _setup_local(tmp_path, monkeypatch)
    from app import routes_groups

    with m._conn() as c:
        c.execute(
            "INSERT INTO groups (id, name, invite_link, is_active) VALUES (?, ?, ?, 1)",
            (41, "cleanup-fixture", "https://max.example/cleanup"),
        )
        c.execute(
            "INSERT INTO profiles (id, phone, status) VALUES (?, ?, ?)",
            (41, "+79990000041", m.ProfileStatus.PENDING),
        )
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, order_index) VALUES (?, ?, ?)",
            (41, 41, 0),
        )

    async def fail_cleanup(_profile_id: int) -> None:
        raise HTTPException(409, "PROFILE_RUNTIME_CLEANUP_FAILED")

    monkeypatch.setattr(routes_groups, "_cleanup_profile_runtime", fail_cleanup)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(routes_groups.remove_group_profile(41, 41))
    assert caught.value.status_code == 409
    with m._conn() as c:
        assert c.execute("SELECT 1 FROM profiles WHERE id=41").fetchone() is not None
        assert c.execute(
            "SELECT 1 FROM group_profiles WHERE group_id=41 AND profile_id=41"
        ).fetchone() is None


def test_admin_proxy_mutation_uses_tenant_busy_guard(monkeypatch):
    from app import routes_admin

    monkeypatch.setattr(routes_admin, "_require_admin", lambda: 1)

    def reject():
        raise HTTPException(409, "Остановите рассылку")

    monkeypatch.setattr(routes_admin.app_main, "_require_worker_idle", reject, raising=False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes_admin.set_group_proxy(7, 3, routes_admin.ProxyIn(proxy="")))
    assert exc.value.status_code == 409


def test_global_group_toggle_stops_workers_before_update(monkeypatch):
    from app import routes_admin

    events = []
    monkeypatch.setattr(routes_admin, "_require_admin", lambda: 1)

    async def stop_workers():
        events.append("stop")

    def update(active):
        events.append(f"update:{active}")
        return {"ok": True}

    monkeypatch.setattr(routes_admin, "_stop_active_tenant_workers", stop_workers, raising=False)
    monkeypatch.setattr(routes_admin, "_bulk_set_groups_active", update)

    assert asyncio.run(routes_admin.deactivate_all_groups()) == {"ok": True}
    assert events == ["stop", "update:0"]
