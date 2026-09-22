"""G-2: admin (impersonating) can set group proxy; cabinet user cannot."""

from __future__ import annotations

import asyncio
import importlib

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
        assert row["proxy"] == proxy

        cleared = asyncio.run(patch_group(gid, GroupPatchIn(proxy="")))
        assert cleared["proxy"] == ""


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
