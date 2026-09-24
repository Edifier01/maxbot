"""Read-only account attention feed for the cabinet dashboard."""

from __future__ import annotations

import asyncio
import importlib


def _setup(tmp_path, monkeypatch):
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


def test_attention_feed_pages_safe_problem_profiles_in_priority_order(tmp_path, monkeypatch):
    m = _setup(tmp_path, monkeypatch)
    from app.routes_dashboard import dashboard_attention

    with m._conn() as connection:
        group_id = connection.execute(
            "INSERT INTO groups (name, invite_link, proxy) VALUES (?, ?, ?)",
            ("fixture", "https://max.example/join/fixture", "socks5://secret:secret@127.0.0.1:1080"),
        ).lastrowid
        profile_ids = {}
        for phone, status, error in (
            ("+79000000001", "active", ""),
            ("+79000000002", "pending", ""),
            ("+79000000003", "needs_reauth", "MAX_SESSION_REVOKED"),
            ("+79000000004", "banned", "MAX_ACCOUNT_BANNED"),
        ):
            profile_id = connection.execute(
                "INSERT INTO profiles (phone, status, last_error) VALUES (?, ?, ?)",
                (phone, status, error),
            ).lastrowid
            connection.execute(
                "INSERT INTO group_profiles (group_id, profile_id) VALUES (?, ?)",
                (group_id, profile_id),
            )
            profile_ids[status] = profile_id
        orphan_id = connection.execute(
            "INSERT INTO profiles (phone, status, last_error) VALUES (?, ?, ?)",
            ("+79000000006", "needs_reauth", "MAX_SESSION_REVOKED"),
        ).lastrowid

    first = asyncio.run(dashboard_attention(offset=0, limit=1))
    rest = asyncio.run(dashboard_attention(offset=1, limit=50))

    assert first["total"] == 4
    assert first["limit"] == 1
    assert first["items"][0]["status"] == "banned"
    assert rest["items"][0]["status"] == "needs_reauth"
    assert rest["items"][1]["status"] == "needs_reauth"
    assert rest["items"][2]["status"] == "pending"
    orphan = next(item for item in rest["items"] if item["id"] == orphan_id)
    assert orphan["primary_group_id"] is None
    assert orphan["linked_group_count"] == 0
    assert all(item["status"] != "active" for item in first["items"] + rest["items"])
    assert all("proxy" not in item for item in first["items"] + rest["items"])
    assert "secret" not in repr((first, rest))


def test_attention_feed_caps_page_size_and_includes_waiting_auth_states(tmp_path, monkeypatch):
    m = _setup(tmp_path, monkeypatch)
    from app.routes_dashboard import dashboard_attention

    with m._conn() as connection:
        group_id = connection.execute(
            "INSERT INTO groups (name, invite_link) VALUES (?, ?)",
            ("fixture", "https://max.example/join/fixture"),
        ).lastrowid
        profile_id = connection.execute(
            "INSERT INTO profiles (phone, status) VALUES (?, ?)",
            ("+79000000005", "pending"),
        ).lastrowid
        connection.execute(
            "INSERT INTO group_profiles (group_id, profile_id) VALUES (?, ?)",
            (group_id, profile_id),
        )
    m._auth_sessions[m._auth_session_key(profile_id)] = {
        "step": "waiting_sms",
        "hint": "Введите SMS-код",
    }

    result = asyncio.run(dashboard_attention(offset=-5, limit=500))

    assert result["offset"] == 0
    assert result["limit"] == 50
    assert result["items"][0]["auth_step"] == "waiting_sms"
