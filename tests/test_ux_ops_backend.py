"""UX-ops backend: group is_active, phone lookup, global pool → tenant queue reset."""

from __future__ import annotations

import asyncio
import importlib
import json
import sqlite3
from datetime import date

import pytest

from app.tenant import tenant_scope
from app.tenant_init import (
    ensure_tenant_data,
    init_global_db,
    init_tenant_db,
)


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


def _setup_server(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    m.reset_test_runtime()
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    return m


def test_global_sqlite_migrates_with_postgres_primary_backend(tmp_path, monkeypatch):
    m = _setup_server(tmp_path, monkeypatch)
    monkeypatch.setattr(m, "DB_BACKEND", "postgres")

    init_global_db(m)
    import app.tenant_init as tenant_init

    startup_init = getattr(tenant_init, "init_startup_db", None)
    assert callable(startup_init)
    startup_init(m)

    with tenant_scope(use_global_data=True, role="admin"):
        with m._conn() as connection:
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
    assert {"settings", "queue_state"} <= tables

    ensure_tenant_data(m.ROOT, 11)
    with tenant_scope(tenant_id=11, role="user"):
        with m._conn() as connection:
            connection.execute("CREATE TABLE tenant_scope_probe (value TEXT)")
            connection.execute("INSERT INTO tenant_scope_probe VALUES ('tenant-11')")
    with tenant_scope(use_global_data=True, role="admin"):
        with m._conn() as connection:
            assert connection.execute(
                "SELECT name FROM sqlite_master WHERE name='tenant_scope_probe'"
            ).fetchone() is None
    with tenant_scope(tenant_id=None, use_global_data=False):
        with pytest.raises(RuntimeError, match="runtime SQLite"):
            m._conn()


def test_onboarding_startup_cleanup_can_read_tenant_sqlite_with_postgres_enabled(
    tmp_path, monkeypatch
):
    m = _setup_server(tmp_path, monkeypatch)
    ensure_tenant_data(m.ROOT, 11)
    with tenant_scope(tenant_id=11, role="admin"):
        m.init_db()
    monkeypatch.setattr(m, "DB_BACKEND", "postgres")

    from app.routes_onboarding import recover_and_cleanup_onboarding

    assert recover_and_cleanup_onboarding() == 0


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
                    "INSERT INTO profiles (id, phone) VALUES (1, ?)",
                    (f"+7900000000{tid}",),
                )
                c.execute("INSERT INTO groups (id, name) VALUES (1, 'reset-test')")
                c.execute(
                    "INSERT INTO send_log (profile_id, group_id, message_idx, status) "
                    "VALUES (1, 1, 5, 'sent')"
                )

    n = m.save_messages_file(b"one\ntwo\nthree\n")
    assert n == 3
    assert m.load_message_pool() == ["one", "two", "three"]
    assert not (m.ROOT / "data" / "global" / "messages" / "active.txt").exists()

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


def test_message_pool_reset_reports_failed_tenant_ids(tmp_path, monkeypatch):
    m = _setup_server(tmp_path, monkeypatch)
    init_global_db(m)
    for tid in (1, 2):
        init_tenant_db(m, tid)

    from app.tenant import get_tenant_id

    original = m._reset_current_queue_for_new_pool

    def flaky_reset(n):
        if get_tenant_id() == 2:
            raise sqlite3.OperationalError("broken tenant db")
        return original(n)

    monkeypatch.setattr(m, "_reset_current_queue_for_new_pool", flaky_reset)

    with pytest.raises(ValueError, match=r"\b2\b"):
        m.save_messages_file(b"one\ntwo\n")
    # A failed tenant reset is fail-closed: the global pool and every tenant
    # queue remain on the previous checkpoint instead of reporting a partial
    # publication as success.
    assert m.load_message_pool() == []
    assert not (m.ROOT / "data" / "global" / "messages" / "active.txt").exists()


def test_existing_empty_tenant_db_is_migrated(tmp_path, monkeypatch):
    m = _setup_server(tmp_path, monkeypatch)
    data_dir = ensure_tenant_data(m.ROOT, 9)
    (data_dir / "app.db").write_bytes(b"")

    init_tenant_db(m, 9)

    with tenant_scope(tenant_id=9, role="user"):
        tables = {
            row["name"]
            for row in m._conn().execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {"profiles", "groups", "settings", "queue_state"} <= tables


def test_send_day_and_dashboard_use_utc_plus_three(tmp_path, monkeypatch):
    m = _setup_local(tmp_path, monkeypatch)
    monkeypatch.setattr(m, "_local_today", lambda: date(2026, 8, 26))
    with m._conn() as c:
        profile_id = c.execute(
            "INSERT INTO profiles (phone, status) VALUES ('+79000000001', 'active')"
        ).lastrowid
        group_id = c.execute(
            "INSERT INTO groups (name, is_active) VALUES ('utc3', 1)"
        ).lastrowid
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, is_enabled) VALUES (?, ?, 1)",
            (group_id, profile_id),
        )
        c.execute(
            "INSERT INTO send_log (profile_id, group_id, message_idx, status, sent_at) "
            "VALUES (?, ?, 0, 'sent', '2026-08-25 21:30:00')",
            (profile_id, group_id),
        )

    assert m._group_sends_today(profile_id, group_id) == 1

    from app.routes_dashboard import dashboard, get_send_log

    body = asyncio.run(dashboard())
    assert body["sent_today"] == 1
    log = asyncio.run(get_send_log())
    assert log["items"][0]["sent_at"] == "2026-08-26 00:30:00"


def test_dashboard_requires_explicit_group_for_ambiguous_profile(tmp_path, monkeypatch):
    m = _setup_local(tmp_path, monkeypatch)
    with m._conn() as c:
        profile_id = c.execute(
            "INSERT INTO profiles (phone, status) VALUES (?, 'active')",
            ("+79000000003",),
        ).lastrowid
        first_group = c.execute(
            "INSERT INTO groups (name, is_active) VALUES ('first', 1)"
        ).lastrowid
        second_group = c.execute(
            "INSERT INTO groups (name, is_active) VALUES ('second', 1)"
        ).lastrowid
        for group_id in (first_group, second_group):
            c.execute(
                "INSERT INTO group_profiles (group_id, profile_id, is_enabled) "
                "VALUES (?, ?, 1)",
                (group_id, profile_id),
            )

    from app.repositories.automation_scope import AutomationScopeRepository
    from app.routes_dashboard import dashboard

    ambiguous = asyncio.run(dashboard())["items"][-1]
    assert ambiguous["linked_group_count"] == 2
    assert ambiguous["primary_group_id"] is None
    assert ambiguous["automation_group_id"] is None

    with m._conn() as c:
        AutomationScopeRepository(c).select_work_group(profile_id, second_group)

    selected = asyncio.run(dashboard())["items"][-1]
    assert selected["linked_group_count"] == 2
    assert selected["automation_group_id"] == second_group
    assert selected["primary_group_id"] == second_group

    with m._conn() as c:
        AutomationScopeRepository(c).unlink_work_group(profile_id)

    unselected = asyncio.run(dashboard())["items"][-1]
    assert unselected["primary_group_id"] is None
    assert unselected["automation_scope_state"] == "unselected"


def test_send_history_keeps_archived_group_rows(tmp_path, monkeypatch):
    """An archived group remains visible in its authorized send history."""
    m = _setup_local(tmp_path, monkeypatch)
    with m._conn() as c:
        profile_id = c.execute(
            "INSERT INTO profiles (phone, status) VALUES (?, 'active')",
            ("+79000000002",),
        ).lastrowid
        group_id = c.execute(
            "INSERT INTO groups (name, is_active) VALUES ('archived', 0)"
        ).lastrowid
        c.execute(
            "INSERT INTO group_profiles (group_id, profile_id, is_enabled) "
            "VALUES (?, ?, 1)",
            (group_id, profile_id),
        )
        c.execute(
            "INSERT INTO send_log (profile_id, group_id, message_idx, status, error) "
            "VALUES (?, ?, 0, 'sent', '')",
            (profile_id, group_id),
        )

    from app.routes_dashboard import get_send_log

    log = asyncio.run(get_send_log())
    assert log["total"] == 1
    assert log["items"][0]["group_id"] == group_id
    assert log["items"][0]["group_name"] == "archived"
