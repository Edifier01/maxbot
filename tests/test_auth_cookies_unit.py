"""Unit tests for auth cookie helpers (no PostgreSQL)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.auth_cookies import AUTH_COOKIE_NAME, clear_auth_cookie, set_auth_cookie


def _request(scheme: str = "http", forwarded_proto: str = "") -> MagicMock:
    req = MagicMock()
    req.url.scheme = scheme
    req.headers = {"x-forwarded-proto": forwarded_proto} if forwarded_proto else {}
    return req


def test_set_auth_cookie_remember_me_includes_max_age():
    from starlette.responses import JSONResponse

    resp = JSONResponse({})
    set_auth_cookie(resp, "jwt-value", remember_me=True, request=_request())
    raw = resp.headers.get("set-cookie", "")
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
    assert "Secure" in resp.headers.get("set-cookie", "")


def test_set_auth_cookie_skipped_when_remember_me_false():
    from starlette.responses import JSONResponse

    resp = JSONResponse({})
    set_auth_cookie(resp, "jwt-value", remember_me=False, request=_request())
    assert "set-cookie" not in resp.headers


def test_clear_auth_cookie_deletes_max_token():
    from starlette.responses import JSONResponse

    resp = JSONResponse({})
    clear_auth_cookie(resp, _request())
    raw = resp.headers.get("set-cookie", "")
    assert AUTH_COOKIE_NAME in raw
    assert "Max-Age=0" in raw
