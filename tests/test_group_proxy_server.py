"""G-2: admin (impersonating) can set group proxy; cabinet user cannot."""

from __future__ import annotations

import asyncio
import importlib
import sqlite3

import pytest
from fastapi import HTTPException

import antiban_core
from app.tenant import tenant_scope


def test_server_mode_patch_group_keeps_proxy(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()

    from app.tenant_init import ensure_tenant_data
    from app.routes_groups import patch_group
    from app.routes_models import GroupPatchIn

    ensure_tenant_data(m.ROOT, 1)
    with tenant_scope(tenant_id=1, role="admin", impersonating=True):
        if not m._db_path().exists():
            m.init_db()
        with m._conn() as c:
            cur = c.execute(
                "INSERT INTO groups (name, invite_link, proxy) VALUES (?, ?, ?)",
                ("G1", "https://max.ru/join/abc", ""),
            )
            gid = int(cur.lastrowid)

        proxy = "socks5://user:pass@203.0.113.10:1080"
        row = asyncio.run(patch_group(gid, GroupPatchIn(proxy=proxy)))
        assert "proxy" not in row
        assert row["proxy_labels"] == ["203.0.113.10:1080"]
        assert "user" not in str(row) and "pass" not in str(row)

        cleared = asyncio.run(patch_group(gid, GroupPatchIn(proxy="")))
        assert "proxy" not in cleared
        assert cleared["proxy_labels"] == []


def test_changing_group_link_invalidates_cached_destination(tmp_path, monkeypatch):
    m = _setup_local(tmp_path, monkeypatch)
    from app.routes_groups import patch_group
    from app.routes_models import GroupPatchIn

    with m._conn() as connection:
        cursor = connection.execute(
            "INSERT INTO groups "
            "(name, invite_link, max_chat_id, destination_verified) "
            "VALUES (?, ?, ?, 1)",
            ("G1", "https://max.example/old", "chat-old"),
        )
        group_id = int(cursor.lastrowid)

    row = asyncio.run(
        patch_group(group_id, GroupPatchIn(invite_link="https://max.example/new"))
    )
    assert row["invite_link"] == "https://max.example/new"
    assert row["max_chat_id"] == ""
    assert row["destination_verified"] == 0
    assert row["destination_revision"] == 1


def test_destination_change_is_blocked_while_manual_test_is_in_progress(
    tmp_path, monkeypatch
):
    m = _setup_local(tmp_path, monkeypatch)
    from app.routes_campaign import CampaignCommandCoordinator
    from app.routes_groups import patch_group
    from app.routes_models import GroupPatchIn

    with m._conn() as connection:
        group_id = int(
            connection.execute(
                "INSERT INTO groups "
                "(name, invite_link, max_chat_id, destination_verified) "
                "VALUES (?, ?, ?, 1)",
                ("G1", "https://max.example/old", "chat-old"),
            ).lastrowid
        )
        coordinator = CampaignCommandCoordinator(connection, scope="local")
        assert coordinator.begin_test("manual-test-route-race").state == "testing"

    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            patch_group(
                group_id,
                GroupPatchIn(invite_link="https://max.example/new"),
            )
        )

    assert caught.value.status_code == 409
    with m._conn() as connection:
        group = connection.execute(
            "SELECT invite_link, max_chat_id, destination_verified, "
            "destination_revision FROM groups WHERE id=?",
            (group_id,),
        ).fetchone()
    assert tuple(group) == ("https://max.example/old", "chat-old", 1, 0)


def test_destination_confirmation_is_blocked_while_manual_test_is_in_progress(
    tmp_path, monkeypatch
):
    m = _setup_local(tmp_path, monkeypatch)
    from app.routes_campaign import CampaignCommandCoordinator
    from app.routes_groups import verify_group_destination
    from app.routes_models import DestinationVerifyIn

    with m._conn() as connection:
        group_id = int(
            connection.execute(
                "INSERT INTO groups "
                "(name, invite_link, max_chat_id, destination_verified) "
                "VALUES (?, ?, ?, 1)",
                ("G1", "https://max.example/old", "chat-old"),
            ).lastrowid
        )
        coordinator = CampaignCommandCoordinator(connection, scope="local")
        assert coordinator.begin_test("manual-test-confirmation-race").state == "testing"

    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            verify_group_destination(
                group_id,
                DestinationVerifyIn(chat_id="chat-new", revision=0),
            )
        )

    assert caught.value.status_code == 409
    with m._conn() as connection:
        group = connection.execute(
            "SELECT invite_link, max_chat_id, destination_verified, "
            "destination_revision FROM groups WHERE id=?",
            (group_id,),
        ).fetchone()
    assert tuple(group) == ("https://max.example/old", "chat-old", 1, 0)


def test_destination_confirmation_is_bound_to_current_link_revision(
    tmp_path, monkeypatch
):
    m = _setup_local(tmp_path, monkeypatch)
    from app.routes_groups import patch_group, verify_group_destination
    from app.routes_models import DestinationVerifyIn, GroupPatchIn

    with m._conn() as connection:
        group_id = int(
            connection.execute(
                "INSERT INTO groups (name, invite_link) VALUES (?, ?)",
                ("G1", "https://max.example/a"),
            ).lastrowid
        )

    confirmed = asyncio.run(
        verify_group_destination(
            group_id, DestinationVerifyIn(chat_id="chat-a", revision=0)
        )
    )
    assert confirmed["max_chat_id"] == "chat-a"
    assert confirmed["destination_verified"] == 1
    assert confirmed["destination_revision"] == 0

    awaitable = patch_group(
        group_id, GroupPatchIn(invite_link="https://max.example/b")
    )
    changed = asyncio.run(awaitable)
    assert changed["destination_revision"] == 1
    assert changed["destination_verified"] == 0

    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            verify_group_destination(
                group_id, DestinationVerifyIn(chat_id="chat-stale", revision=0)
            )
        )
    assert caught.value.status_code == 409
    assert caught.value.detail == "DESTINATION_REVIEW_REQUIRED"

    confirmed_new = asyncio.run(
        verify_group_destination(
            group_id, DestinationVerifyIn(chat_id="chat-b", revision=1)
        )
    )
    assert confirmed_new["max_chat_id"] == "chat-b"
    assert confirmed_new["destination_revision"] == 1


def _setup_local(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    import app.config as cfg
    import app.sqlite_backend as sqlite_backend

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    sqlite_backend.reset_connections()
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.init_db()
    return m


def test_schema_backfills_roll_back_together_on_interruption(tmp_path, monkeypatch):
    m = _setup_local(tmp_path, monkeypatch)
    import app.sqlite_backend as sqlite_backend

    with m._conn() as connection:
        profile_id = connection.execute(
            "INSERT INTO profiles (phone, proxy) VALUES (?, ?)",
            ("+79990000001", "socks5://proxy.example:1080"),
        ).lastrowid
        group_id = connection.execute(
            "INSERT INTO groups (name, invite_link) VALUES (?, ?)",
            ("legacy", "https://max.ru/join/legacy"),
        ).lastrowid
        connection.execute(
            "INSERT INTO group_profiles (group_id, profile_id, is_enabled) "
            "VALUES (?, ?, 1)",
            (group_id, profile_id),
        )
        for column in ("destination_verified", "destination_revision", "proxy"):
            connection.execute(f"ALTER TABLE groups DROP COLUMN {column}")
        connection.execute("UPDATE groups SET max_chat_id='chat-legacy'")

    class FailOnBackfill:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def execute(self, sql, *args):
            if "UPDATE groups SET destination_verified=1" in sql:
                raise sqlite3.OperationalError("simulated interruption during backfill")
            return self.wrapped.execute(sql, *args)

        def executescript(self, sql):
            return self.wrapped.executescript(sql)

    with m._conn() as connection:
        with pytest.raises(sqlite3.OperationalError, match="simulated interruption"):
            sqlite_backend._migrate_schema(FailOnBackfill(connection))

        columns = sqlite_backend._table_columns(connection, "groups")
        assert "destination_revision" not in columns
        assert "destination_verified" not in columns
        assert "proxy" not in columns

        sqlite_backend._migrate_schema(connection)
        row = connection.execute(
            "SELECT destination_verified, proxy FROM groups WHERE id=?", (group_id,)
        ).fetchone()
        assert row["destination_verified"] == 1
        assert row["proxy"] == "socks5://proxy.example:1080"


def test_schema_repairs_legacy_destination_column_with_incomplete_backfill(
    tmp_path, monkeypatch
):
    m = _setup_local(tmp_path, monkeypatch)
    import app.sqlite_backend as sqlite_backend

    with m._conn() as connection:
        group_id = connection.execute(
            "INSERT INTO groups (name, invite_link, max_chat_id, destination_verified) "
            "VALUES (?, ?, ?, 0)",
            ("interrupted-legacy", "https://max.ru/join/legacy", "chat-legacy"),
        ).lastrowid

        sqlite_backend._migrate_group_destination_and_proxy(connection)

        row = connection.execute(
            "SELECT destination_verified FROM groups WHERE id=?", (group_id,)
        ).fetchone()
        assert row["destination_verified"] == 1


def test_campaign_start_server_mode_empty_proxy_400(tmp_path, monkeypatch):
    m = _setup_local(tmp_path, monkeypatch)
    with m._conn() as c:
        c.execute(
            "INSERT INTO groups (name, invite_link, proxy) VALUES (?, ?, ?)",
            ("G1", "https://max.ru/join/abc", ""),
        )
    data_dir = m._resolve_data_dir()
    monkeypatch.setattr(m, "_is_server_mode", lambda: True)
    monkeypatch.setattr(m, "_resolve_data_dir", lambda: data_dir)
    monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
    monkeypatch.setattr(m, "load_message_pool", lambda: ["hi"])
    monkeypatch.setattr(m, "_has_active_profiles", lambda: True)
    monkeypatch.setattr(m, "_has_sendable_profile", lambda: True)

    from app.routes_campaign import campaign_start

    with pytest.raises(HTTPException) as ei:
        asyncio.run(campaign_start())
    assert ei.value.status_code == 400
    assert "прокси" in str(ei.value.detail).lower()
    assert m.get_setting("auto_run") in ("", "0")


def test_pymax_extra_config_keeps_proxy_and_effective_target():
    from app.services.pymax_runtime import build_extra_config

    extra = build_extra_config(
        proxy="socks5://fixture-user:fixture-pass@203.0.113.10:1080",
        identity=None,
    )
    assert extra.proxy == "socks5://fixture-user:fixture-pass@203.0.113.10:1080"
    assert extra.host == "api2.oneme.ru"
    assert extra.port == 443
    assert extra.reconnect is False
    assert extra.relogin is False
    assert extra.telemetry is False


def test_group_preflight_checks_every_pool_member(tmp_path, monkeypatch):
    m = _setup_local(tmp_path, monkeypatch)
    raw = "socks5://one.example:1080\nsocks5://two.example:1080"
    with m._conn() as c:
        gid = c.execute(
            "INSERT INTO groups (name, invite_link, proxy) VALUES ('G', 'x', ?)",
            (raw,),
        ).lastrowid
    calls = []

    def check(url, **_kwargs):
        calls.append(url)
        return (not url.startswith("socks5://two"), "second failed")

    monkeypatch.setattr(m.antiban_core, "check_proxy", check)
    m._proxy_bad_until.clear()
    ok, error = m._validate_proxy_for_group({"id": gid, "name": "G"}, None)

    assert ok is False
    assert "two.example" in error
    assert "second failed" in error
    assert calls == antiban_core.parse_proxy_list(raw)


def test_proxy_bad_cache_is_tenant_scoped(tmp_path, monkeypatch):
    m = _setup_local(tmp_path, monkeypatch)
    proxy = "socks5://proxy.example:1080"
    monkeypatch.setattr(m, "_is_server_mode", lambda: True)
    monkeypatch.setattr(m, "_group_proxy_raw", lambda _gid: proxy)
    monkeypatch.setattr(m, "append_log", lambda _msg: None)
    monkeypatch.setattr(m, "_schedule_telegram", lambda *_args, **_kwargs: None)
    calls = []
    monkeypatch.setattr(
        m.antiban_core,
        "check_proxy",
        lambda url, **_kwargs: (calls.append(url) is None and False, "down"),
    )
    m._proxy_bad_until.clear()

    with tenant_scope(tenant_id=1, role="admin"):
        assert m._validate_proxy_for_group({"id": 1, "name": "G"}, None)[0] is False
    with tenant_scope(tenant_id=2, role="admin"):
        assert m._validate_proxy_for_group({"id": 1, "name": "G"}, None)[0] is False

    assert calls == [proxy, proxy]
