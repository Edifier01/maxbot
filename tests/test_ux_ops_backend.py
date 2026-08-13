"""UX-ops backend: group is_active, phone lookup, global pool → tenant queue reset."""

from __future__ import annotations

import importlib
import json

from app.tenant import tenant_scope
from app.tenant_init import ensure_tenant_data, init_global_db, init_tenant_db


def _setup_local(tmp_path, monkeypatch):
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


def _setup_server(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    return m


def test_patch_is_active_and_campaign_requires_active_groups(tmp_path, monkeypatch):
    m = _setup_local(tmp_path, monkeypatch)
    from starlette.testclient import TestClient

    with TestClient(m.app) as client:
        created = client.post(
            "/api/groups",
            json={"name": "G1", "invite_link": "https://max.ru/join/abc"},
        )
        assert created.status_code == 200
        gid = created.json()["id"]

        listed = client.get("/api/groups")
        assert listed.status_code == 200
        assert listed.json()[0]["is_active"] == 1
        assert len(m._active_groups()) == 1

        off = client.patch(f"/api/groups/{gid}", json={"is_active": 0})
        assert off.status_code == 200
        assert off.json()["is_active"] == 0
        assert m._active_groups() == []
        listed_off = client.get("/api/groups").json()
        assert listed_off[0]["is_active"] == 0

        on = client.patch(f"/api/groups/{gid}", json={"is_active": 1})
        assert on.status_code == 200
        assert on.json()["is_active"] == 1
        assert len(m._active_groups()) == 1

        client.patch(f"/api/groups/{gid}", json={"is_active": 0})
        monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
        monkeypatch.setattr(m, "load_message_pool", lambda: ["hi"])
        monkeypatch.setattr(m, "_has_active_profiles", lambda: True)
        monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)
        start = client.post("/api/campaign/start")
        assert start.status_code == 400
        assert "групп" in start.json()["detail"].lower()


def test_campaign_start_empty_pool_asks_admin(tmp_path, monkeypatch):
    m = _setup_local(tmp_path, monkeypatch)
    from starlette.testclient import TestClient

    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m, "load_message_pool", lambda: [])
    with TestClient(m.app) as client:
        start = client.post("/api/campaign/start")
    assert start.status_code == 400
    detail = start.json()["detail"]
    assert "Нет файла сообщений" in detail
    assert "администратору" in detail.lower()


def test_list_group_profiles_phone_finds_past_page_cap(tmp_path, monkeypatch):
    m = _setup_local(tmp_path, monkeypatch)
    from starlette.testclient import TestClient

    with m._conn() as c:
        cur = c.execute(
            "INSERT INTO groups (name, invite_link) VALUES (?, ?)",
            ("G1", "https://max.ru/join/abc"),
        )
        gid = int(cur.lastrowid)
        for i in range(120):
            phone = f"+79000000{i:03d}"
            pcur = c.execute(
                "INSERT INTO profiles (phone, label, status) VALUES (?, ?, ?)",
                (phone, f"p{i}", m.ProfileStatus.PENDING),
            )
            pid = int(pcur.lastrowid)
            c.execute(
                "INSERT INTO group_profiles (group_id, profile_id, order_index) "
                "VALUES (?, ?, ?)",
                (gid, pid, i),
            )

    target = "+79000000110"
    with TestClient(m.app) as client:
        paged = client.get(f"/api/groups/{gid}/profiles", params={"offset": 0, "limit": 500})
        assert paged.status_code == 200
        body = paged.json()
        assert body["total"] == 120
        assert len(body["items"]) == 100
        assert all(p["phone"] != target for p in body["items"])

        found = client.get(
            f"/api/groups/{gid}/profiles",
            params={"phone": "89000000110", "offset": 0, "limit": 20},
        )
        assert found.status_code == 200
        data = found.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["phone"] == target


def test_save_messages_resets_all_tenant_queue_indices(tmp_path, monkeypatch):
    m = _setup_server(tmp_path, monkeypatch)
    init_global_db(m)
    for tid in (1, 2):
        ensure_tenant_data(m.ROOT, tid)
        init_tenant_db(m, tid)
        with tenant_scope(tenant_id=tid, role="user"):
            with m._conn() as c:
                c.execute(
                    "UPDATE queue_state SET profile_idx=3, message_idx=9, "
                    "group_idx=2, message_bag=? WHERE id=1",
                    (json.dumps([7, 8, 9]),),
                )
                c.execute(
                    "INSERT INTO send_log (profile_id, group_id, message_idx, status) "
                    "VALUES (1, 1, 5, 'sent')"
                )

    n = m.save_messages_file(b"one\ntwo\nthree\n")
    assert n == 3
    assert m.load_message_pool() == ["one", "two", "three"]

    for tid in (1, 2):
        with tenant_scope(tenant_id=tid, role="user"):
            with m._conn() as c:
                qs = c.execute(
                    "SELECT profile_idx, message_idx, group_idx, message_bag "
                    "FROM queue_state WHERE id=1"
                ).fetchone()
                send_n = c.execute("SELECT COUNT(*) n FROM send_log").fetchone()["n"]
            assert qs["message_idx"] == 0
            assert qs["profile_idx"] == 0
            assert qs["group_idx"] == 0
            bag = json.loads(qs["message_bag"] or "[]")
            assert sorted(bag) == [0, 1, 2]
            assert send_n == 1
