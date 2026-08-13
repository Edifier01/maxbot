"""FEATURE-REVIEW-FIX-2026: cabinet AuthZ, impersonation admin lock, subscription gate."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app import auth_rate_limit
from app.tenant import tenant_scope


@pytest.fixture
def auth_mw(monkeypatch):
    monkeypatch.setattr("app.middleware.is_server_mode", lambda: True)
    monkeypatch.setattr("app.middleware.INTERNAL_SERVICE_TOKEN", "")
    from app import auth
    from app.middleware import ServerAuthMiddleware

    auth.clear_session_cache()
    auth_rate_limit.reset_memory_limits()
    return ServerAuthMiddleware(app=MagicMock())


def _request(path: str, method: str = "GET") -> MagicMock:
    req = MagicMock()
    req.method = method
    req.url.path = path
    req.headers = {"Authorization": "Bearer jwt-token"}
    req.cookies = {}
    req.client = MagicMock()
    req.client.host = "10.0.0.1"
    return req


def _dispatch(auth_mw, payload: dict, path: str, method: str = "GET", *, sub_active=True):
    async def run():
        call_next = AsyncMock(return_value="ok")
        with patch("app.middleware.decode_token", return_value=payload), patch(
            "app.middleware.cached_validate_token_session", return_value=None
        ), patch("app.middleware.db_pg.subscription_active", return_value=sub_active):
            resp = await auth_mw.dispatch(_request(path, method), call_next)
        return resp, call_next

    return asyncio.run(run())


USER = {"sub": "1", "role": "user", "tenant_id": 2, "jti": "u", "tv": 0}
ADMIN = {"sub": "9", "role": "admin", "tenant_id": None, "jti": "a", "tv": 0}
ADMIN_IMP = {
    "sub": "9",
    "role": "admin",
    "tenant_id": 2,
    "jti": "i",
    "tv": 0,
    "imp": True,
}


def test_user_pause_forbidden(auth_mw):
    resp, call_next = _dispatch(auth_mw, USER, "/api/campaign/pause", "POST")
    assert resp.status_code == 403
    assert "личном кабинете" in resp.body.decode()
    call_next.assert_not_awaited()


def test_user_get_messages_forbidden(auth_mw):
    resp, call_next = _dispatch(auth_mw, USER, "/api/messages")
    assert resp.status_code == 403
    assert "личном кабинете" in resp.body.decode()
    call_next.assert_not_awaited()


def test_user_get_settings_forbidden(auth_mw):
    resp, call_next = _dispatch(auth_mw, USER, "/api/settings")
    assert resp.status_code == 403
    call_next.assert_not_awaited()


def test_user_start_inactive_subscription_forbidden(auth_mw):
    resp, call_next = _dispatch(
        auth_mw, USER, "/api/campaign/start", "POST", sub_active=False
    )
    assert resp.status_code == 403
    assert "Подписка" in resp.body.decode()
    call_next.assert_not_awaited()


def test_user_retry_failed_inactive_subscription_forbidden(auth_mw):
    resp, call_next = _dispatch(
        auth_mw, USER, "/api/campaign/retry_failed", "POST", sub_active=False
    )
    assert resp.status_code == 403
    call_next.assert_not_awaited()


def test_user_test_inactive_subscription_forbidden(auth_mw):
    resp, call_next = _dispatch(
        auth_mw, USER, "/api/campaign/test", "POST", sub_active=False
    )
    assert resp.status_code == 403
    call_next.assert_not_awaited()


def test_user_stop_allowed(auth_mw):
    resp, call_next = _dispatch(auth_mw, USER, "/api/campaign/stop", "POST")
    assert resp == "ok"
    call_next.assert_awaited_once()


def test_user_start_active_subscription_allowed(auth_mw):
    resp, call_next = _dispatch(
        auth_mw, USER, "/api/campaign/start", "POST", sub_active=True
    )
    assert resp == "ok"
    call_next.assert_awaited_once()


def test_admin_imp_admin_api_forbidden(auth_mw):
    resp, call_next = _dispatch(auth_mw, ADMIN_IMP, "/api/admin/users")
    assert resp.status_code == 403
    assert "impersonation" in resp.body.decode().lower()
    call_next.assert_not_awaited()


def test_admin_without_imp_admin_api_allowed(auth_mw):
    resp, call_next = _dispatch(auth_mw, ADMIN, "/api/admin/users")
    assert resp == "ok"
    call_next.assert_awaited_once()


def test_admin_imp_pause_allowed(auth_mw):
    resp, call_next = _dispatch(auth_mw, ADMIN_IMP, "/api/campaign/pause", "POST")
    assert resp == "ok"
    call_next.assert_awaited_once()


def test_require_admin_rejects_impersonating():
    from app.routes_admin import _require_admin

    with tenant_scope(user_id=1, role="admin", impersonating=True):
        with pytest.raises(HTTPException) as ei:
            _require_admin()
        assert ei.value.status_code == 403

    with tenant_scope(user_id=1, role="admin", impersonating=False):
        assert _require_admin() == 1


def _setup_tenant_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")
    import importlib

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()

    from app.tenant_init import ensure_tenant_data

    ensure_tenant_data(m.ROOT, 1)
    return m


def test_user_cannot_patch_group_is_active_or_proxy(tmp_path, monkeypatch):
    m = _setup_tenant_db(tmp_path, monkeypatch)
    from app.routes_groups import add_group, bulk_add_group_profiles, patch_group
    from app.routes_models import BulkProfilesIn, GroupIn, GroupPatchIn, ProfileIn

    with tenant_scope(tenant_id=1, role="user"):
        if not m._db_path().exists():
            m.init_db()
        created = asyncio.run(
            add_group(GroupIn(name="G1", invite_link="https://max.ru/join/abc"))
        )
        gid = int(created["id"])

        with pytest.raises(HTTPException) as ei_active:
            asyncio.run(patch_group(gid, GroupPatchIn(is_active=0)))
        assert ei_active.value.status_code == 403

        with pytest.raises(HTTPException) as ei_proxy:
            asyncio.run(
                patch_group(
                    gid,
                    GroupPatchIn(proxy="socks5://user:pass@203.0.113.10:1080"),
                )
            )
        assert ei_proxy.value.status_code == 403

        with pytest.raises(HTTPException) as ei_create_proxy:
            asyncio.run(
                add_group(
                    GroupIn(
                        name="G2",
                        invite_link="https://max.ru/join/def",
                        proxy="socks5://user:pass@203.0.113.10:1080",
                    )
                )
            )
        assert ei_create_proxy.value.status_code == 403

        with pytest.raises(HTTPException) as ei_bulk:
            asyncio.run(
                bulk_add_group_profiles(
                    gid,
                    BulkProfilesIn(profiles=[ProfileIn(phone="+79001234567")]),
                )
            )
        assert ei_bulk.value.status_code == 403

        renamed = asyncio.run(patch_group(gid, GroupPatchIn(name="Renamed")))
        assert renamed["name"] == "Renamed"
        assert renamed["is_active"] == 1
        assert renamed["proxy"] == ""


def test_admin_imp_can_patch_group_proxy(tmp_path, monkeypatch):
    m = _setup_tenant_db(tmp_path, monkeypatch)
    from app.routes_groups import patch_group
    from app.routes_models import GroupPatchIn

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
        off = asyncio.run(patch_group(gid, GroupPatchIn(is_active=0)))
        assert off["is_active"] == 0


def test_is_cabinet_user_role_and_impersonation():
    from app.tenant import is_cabinet_user

    with tenant_scope(user_id=1, tenant_id=2, role="user"):
        assert is_cabinet_user()
    with tenant_scope(user_id=1, tenant_id=2, role="user", impersonating=True):
        assert not is_cabinet_user()
    with tenant_scope(user_id=9, role="admin"):
        assert not is_cabinet_user()


def test_user_cannot_patch_profile_proxy(tmp_path, monkeypatch):
    m = _setup_tenant_db(tmp_path, monkeypatch)
    from app.routes_models import ProfilePatchIn
    from app.routes_profiles import patch_profile

    with tenant_scope(tenant_id=1, role="user"):
        if not m._db_path().exists():
            m.init_db()
        with m._conn() as c:
            cur = c.execute(
                "INSERT INTO profiles (phone, label, status, proxy) VALUES (?, ?, ?, ?)",
                ("+79001234567", "A", m.ProfileStatus.PENDING, ""),
            )
            pid = int(cur.lastrowid)

        with pytest.raises(HTTPException) as ei_proxy:
            asyncio.run(
                patch_profile(
                    pid,
                    ProfilePatchIn(proxy="socks5://user:pass@203.0.113.10:1080"),
                )
            )
        assert ei_proxy.value.status_code == 403
        assert "личном кабинете" in str(ei_proxy.value.detail)

        renamed = asyncio.run(patch_profile(pid, ProfilePatchIn(label="Renamed")))
        assert renamed["label"] == "Renamed"
        assert renamed["proxy"] == ""


def test_user_cannot_add_phone_with_proxy(tmp_path, monkeypatch):
    m = _setup_tenant_db(tmp_path, monkeypatch)
    from app.routes_groups import add_group, add_group_profile
    from app.routes_models import GroupIn, ProfileIn

    with tenant_scope(tenant_id=1, role="user"):
        if not m._db_path().exists():
            m.init_db()
        created = asyncio.run(
            add_group(GroupIn(name="G1", invite_link="https://max.ru/join/abc"))
        )
        gid = int(created["id"])

        with pytest.raises(HTTPException) as ei_proxy:
            asyncio.run(
                add_group_profile(
                    gid,
                    ProfileIn(
                        phone="+79001234567",
                        proxy="socks5://user:pass@203.0.113.10:1080",
                    ),
                )
            )
        assert ei_proxy.value.status_code == 403
        assert "личном кабинете" in str(ei_proxy.value.detail)

        added = asyncio.run(
            add_group_profile(gid, ProfileIn(phone="+79001234567", label="A"))
        )
        assert added["id"]
        assert added["phone"] == "+79001234567"
        with m._conn() as c:
            row = c.execute(
                "SELECT proxy FROM profiles WHERE id=?", (added["id"],)
            ).fetchone()
        assert row["proxy"] == ""


def test_admin_imp_can_patch_profile_proxy(tmp_path, monkeypatch):
    m = _setup_tenant_db(tmp_path, monkeypatch)
    from app.routes_models import ProfilePatchIn
    from app.routes_profiles import patch_profile

    with tenant_scope(tenant_id=1, role="admin", impersonating=True):
        if not m._db_path().exists():
            m.init_db()
        with m._conn() as c:
            cur = c.execute(
                "INSERT INTO profiles (phone, label, status, proxy) VALUES (?, ?, ?, ?)",
                ("+79001234567", "A", m.ProfileStatus.PENDING, ""),
            )
            pid = int(cur.lastrowid)
        proxy = "socks5://user:pass@203.0.113.10:1080"
        row = asyncio.run(patch_profile(pid, ProfilePatchIn(proxy=proxy)))
        assert row["proxy"] == proxy


def test_server_mode_vault_password_endpoints_gone(tmp_path, monkeypatch):
    m = _setup_tenant_db(tmp_path, monkeypatch)
    from app.routes_vault import (
        VaultPasswordIn,
        api_vault_lock,
        api_vault_setup,
        api_vault_status,
        api_vault_unlock,
    )

    with tenant_scope(tenant_id=1, role="admin"):
        st = asyncio.run(api_vault_status())
        assert isinstance(st, dict)
        assert "unlocked" in st

        body = VaultPasswordIn(password="test-password")
        for coro in (
            api_vault_setup(body),
            api_vault_unlock(body),
            api_vault_lock(),
        ):
            with pytest.raises(HTTPException) as ei:
                asyncio.run(coro)
            assert ei.value.status_code == 410
            assert ".app_key" in str(ei.value.detail)


def test_desktop_vault_setup_not_gone(monkeypatch):
    from app.routes_vault import VaultPasswordIn, api_vault_setup
    from app.runtime import main as rv_main

    monkeypatch.setattr(rv_main, "_is_server_mode", lambda: False)
    monkeypatch.setattr(rv_main, "setup_vault", lambda password: {"ok": True})
    result = asyncio.run(api_vault_setup(VaultPasswordIn(password="desktop-pass")))
    assert result == {"ok": True}
