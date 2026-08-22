"""Unit tests for auth cookie helpers (no PostgreSQL)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.auth_cookies import (
    ADMIN_BACKUP_COOKIE_NAME,
    AUTH_COOKIE_NAME,
    clear_admin_backup_cookie,
    clear_auth_cookie,
    set_admin_backup_cookie,
    set_auth_cookie,
)


def _request(scheme: str = "http", forwarded_proto: str = "") -> MagicMock:
    req = MagicMock()
    req.url.scheme = scheme
    req.headers = {"x-forwarded-proto": forwarded_proto} if forwarded_proto else {}
    return req


def _set_cookie_header(resp) -> str:
    if hasattr(resp.headers, "getlist"):
        return "\n".join(resp.headers.getlist("set-cookie"))
    return resp.headers.get("set-cookie", "")


def test_set_auth_cookie_remember_me_includes_max_age():
    from starlette.responses import JSONResponse

    resp = JSONResponse({})
    set_auth_cookie(resp, "jwt-value", remember_me=True, request=_request())
    raw = _set_cookie_header(resp)
    assert f"{AUTH_COOKIE_NAME}=jwt-value" in raw
    assert "HttpOnly" in raw
    assert "Max-Age=604800" in raw
    assert "Secure" not in raw


def test_set_auth_cookie_secure_behind_proxy():
    from starlette.responses import JSONResponse

    resp = JSONResponse({})
    set_auth_cookie(
        resp,
        "jwt-value",
        remember_me=True,
        request=_request(scheme="http", forwarded_proto="https"),
    )
    assert "Secure" in _set_cookie_header(resp)


def test_set_auth_cookie_session_when_remember_me_false():
    from starlette.responses import JSONResponse

    resp = JSONResponse({})
    set_auth_cookie(resp, "jwt-value", remember_me=False, request=_request())
    raw = _set_cookie_header(resp)
    assert f"{AUTH_COOKIE_NAME}=jwt-value" in raw
    assert "HttpOnly" in raw
    assert "Max-Age" not in raw


def test_set_admin_backup_cookie_is_session():
    from starlette.responses import JSONResponse

    resp = JSONResponse({})
    set_admin_backup_cookie(resp, "admin-jwt", request=_request())
    raw = _set_cookie_header(resp)
    assert f"{ADMIN_BACKUP_COOKIE_NAME}=admin-jwt" in raw
    assert "HttpOnly" in raw
    assert "Max-Age" not in raw


def test_clear_auth_cookie_deletes_max_token():
    from starlette.responses import JSONResponse

    resp = JSONResponse({})
    clear_auth_cookie(resp, _request())
    raw = _set_cookie_header(resp)
    assert AUTH_COOKIE_NAME in raw
    assert "Max-Age=0" in raw


def test_clear_admin_backup_cookie_deletes_backup():
    from starlette.responses import JSONResponse

    resp = JSONResponse({})
    clear_admin_backup_cookie(resp, _request())
    raw = _set_cookie_header(resp)
    assert ADMIN_BACKUP_COOKIE_NAME in raw
    assert "Max-Age=0" in raw


def test_public_registration_route_is_removed():
    from app.routes_auth import router

    assert "/api/auth/register" not in {route.path for route in router.routes}


def test_exit_impersonation_fails_closed_without_admin_cookie(monkeypatch):
    monkeypatch.setattr("app.routes_auth.is_server_mode", lambda: True)
    from app.routes_auth import exit_impersonation

    req = MagicMock()
    req.cookies = {}
    with pytest.raises(HTTPException) as ei:
        asyncio.run(exit_impersonation(req))
    assert ei.value.status_code == 401


def test_exit_impersonation_rejects_imp_backup_cookie(monkeypatch):
    monkeypatch.setattr("app.routes_auth.is_server_mode", lambda: True)
    from app.routes_auth import exit_impersonation

    req = MagicMock()
    req.cookies = {"max_admin_token": "imp-jwt"}
    with patch(
        "app.routes_auth.auth.decode_token",
        return_value={"imp": True, "sub": "1"},
    ):
        with pytest.raises(HTTPException) as ei:
            asyncio.run(exit_impersonation(req))
    assert ei.value.status_code == 401


def test_restore_session_rejects_imp_cookie(monkeypatch):
    monkeypatch.setattr("app.routes_auth.is_server_mode", lambda: True)
    from app.routes_auth import restore_session

    req = MagicMock()
    req.cookies = {"max_token": "imp-jwt"}
    with patch(
        "app.routes_auth.auth.decode_token",
        return_value={"imp": True, "sub": "1"},
    ):
        with pytest.raises(HTTPException) as ei:
            asyncio.run(restore_session(req))
    assert ei.value.status_code == 401
