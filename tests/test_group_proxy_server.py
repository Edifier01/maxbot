"""G-2: tenant can set group proxy in server mode via PATCH /api/groups."""

from __future__ import annotations

import asyncio
import importlib

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
    with tenant_scope(tenant_id=1, role="user"):
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
