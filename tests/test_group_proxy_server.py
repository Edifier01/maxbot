"""G-2: admin (impersonating) can set group proxy; cabinet user cannot."""

from __future__ import annotations

import asyncio
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

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


def test_extra_config_proxy_typeerror_fails_closed(tmp_path, monkeypatch):
    m = _setup_local(tmp_path, monkeypatch)
    logs: list[str] = []
    monkeypatch.setattr(m, "append_log", logs.append)
    monkeypatch.setattr(m, "_session_db_has_token", lambda _id: True)
    monkeypatch.setattr(m, "_decrypt_session", lambda _id: None)
    monkeypatch.setattr(m, "_encrypt_session", lambda _id: None)
    monkeypatch.setattr(m, "_session_device_fields", lambda _id: (None, None))
    monkeypatch.setattr(m, "_safe_stop", AsyncMock())

    class NoProxyExtra:
        def __init__(self, **kwargs):
            if "proxy" in kwargs:
                raise TypeError("unexpected keyword argument 'proxy'")

    monkeypatch.setitem(
        sys.modules,
        "pymax",
        SimpleNamespace(Client=object, ExtraConfig=NoProxyExtra),
    )

    async def _run():
        await m._with_client(
            1,
            "+79991112233",
            lambda _c: None,
            proxy="socks5://u:p@203.0.113.10:1080",
        )

    with pytest.raises(RuntimeError, match="прокси"):
        asyncio.run(_run())
    assert not any("работаем без него" in line for line in logs)
