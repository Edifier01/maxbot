"""Remember-me persistent login: HttpOnly cookie + restore-session."""

from __future__ import annotations

import os
import re
import uuid

import pytest
from conftest import requires_postgres

pytestmark = requires_postgres


def _truncate_saas() -> None:
    from app import db_pg

    db_pg.close()
    db_pg.init_schema()
    with db_pg._cursor(transaction=True) as cur:
        cur.execute(
            """
            TRUNCATE revoked_tokens, impersonation_log, subscriptions, users, tenants
            RESTART IDENTITY CASCADE
            """
        )


def _tok(token: str) -> dict[str, str]:
    return {"max_token": token}


def _cookie_token(resp) -> str:
    token = resp.cookies.get("max_token")
    assert token
    return token


def _set_cookie_headers(resp) -> list[str]:
    headers = resp.headers
    if hasattr(headers, "get_list"):
        return headers.get_list("set-cookie")
    raw = headers.get("set-cookie", "")
    return [raw] if raw else []


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    uid = uuid.uuid4().hex[:8]
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("JWT_SECRET", "remember-me-jwt-secret-min-32-chars")
    monkeypatch.setenv("JWT_EXPIRE_HOURS", "168")
    monkeypatch.setenv("ADMIN_EMAIL", f"admin-{uid}@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "AdminPass123!")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)

    import main as m

    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()

    from app import db_pg
    from app.hooks import before_start
    from app.middleware import AuthRateLimitMiddleware

    AuthRateLimitMiddleware._counters.clear()
    _truncate_saas()
    before_start()
    m.reset_test_runtime()

    from starlette.testclient import TestClient

    with TestClient(m.app) as client:
        yield client, uid

    db_pg.close()


def _register_user(client, uid: str):
    admin = client.post(
        "/api/auth/login",
        json={"login": os.environ["ADMIN_EMAIL"], "password": "AdminPass123!"},
    )
    assert admin.status_code == 200, admin.text
    return client.post(
        "/api/admin/users",
        cookies=_tok(_cookie_token(admin)),
        json={
            "institution_name": f"School {uid}",
            "login": f"user-{uid}@example.com",
            "password": "UserPass123!",
        },
    )


def test_login_remember_me_sets_httponly_cookie(auth_client):
    client, uid = auth_client
    reg = _register_user(client, uid)
    assert reg.status_code == 200

    login = client.post(
        "/api/auth/login",
        json={
            "login": f"user-{uid}@example.com",
            "password": "UserPass123!",
            "remember_me": True,
        },
    )
    assert login.status_code == 200
    assert "token" not in login.json()
    set_cookie = login.headers.get("set-cookie", "")
    assert "max_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie or "SameSite=Lax" in set_cookie
    assert "Max-Age=604800" in set_cookie  # 168h * 3600


def test_login_remember_me_false_no_persistent_cookie(auth_client):
    client, uid = auth_client
    _register_user(client, uid)

    login = client.post(
        "/api/auth/login",
        json={
            "login": f"user-{uid}@example.com",
            "password": "UserPass123!",
            "remember_me": False,
        },
    )
    assert login.status_code == 200
    set_cookie = "\n".join(_set_cookie_headers(login))
    assert "max_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Max-Age" not in set_cookie


def test_restore_session_with_valid_cookie(auth_client):
    client, uid = auth_client
    _register_user(client, uid)

    login = client.post(
        "/api/auth/login",
        json={
            "login": f"user-{uid}@example.com",
            "password": "UserPass123!",
            "remember_me": True,
        },
    )
    assert login.status_code == 200
    assert _cookie_token(login)

    restore = client.post("/api/auth/restore-session")
    assert restore.status_code == 200
    body = restore.json()
    assert "token" not in body
    assert body["email"] == f"user-{uid}@example.com"
    assert body["role"] == "user"


def test_restore_session_without_cookie_401(auth_client):
    client, _uid = auth_client
    restore = client.post("/api/auth/restore-session")
    assert restore.status_code == 401


def test_logout_clears_cookie(auth_client):
    client, uid = auth_client
    _register_user(client, uid)

    login = client.post(
        "/api/auth/login",
        json={
            "login": f"user-{uid}@example.com",
            "password": "UserPass123!",
            "remember_me": True,
        },
    )
    assert login.status_code == 200
    assert "max_token=" in login.headers.get("set-cookie", "")

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    set_cookie = "\n".join(_set_cookie_headers(logout))
    assert re.search(r"max_token=.*Max-Age=0|max_token=;\s*Max-Age=0", set_cookie)

    restore = client.post("/api/auth/restore-session")
    assert restore.status_code == 401


def test_impersonate_does_not_set_persistent_cookie(auth_client):
    client, uid = auth_client
    reg = _register_user(client, uid)
    tenant_id = reg.json()["tenant_id"]
    admin_email = os.environ["ADMIN_EMAIL"]

    admin_login = client.post(
        "/api/auth/login",
        json={"login": admin_email, "password": "AdminPass123!", "remember_me": True},
    )
    assert admin_login.status_code == 200
    admin_token = _cookie_token(admin_login)

    imp = client.post(
        f"/api/admin/impersonate/{tenant_id}",
        cookies=_tok(admin_token),
    )
    assert imp.status_code == 200
    headers = _set_cookie_headers(imp)
    joined = "\n".join(headers)
    assert "max_token=" in joined
    max_token_hdr = next(h for h in headers if h.startswith("max_token="))
    assert "HttpOnly" in max_token_hdr
    assert "Max-Age" not in max_token_hdr
    assert "max_admin_token=" in joined
    admin_hdr = next(h for h in headers if h.startswith("max_admin_token="))
    assert "HttpOnly" in admin_hdr
    assert "Max-Age" not in admin_hdr

    restore_imp = client.post("/api/auth/restore-session")
    assert restore_imp.status_code == 401

    exited = client.post("/api/auth/exit-impersonation")
    assert exited.status_code == 200
    assert exited.json()["email"] == admin_email
    assert exited.json()["role"] == "admin"
    exit_joined = "\n".join(_set_cookie_headers(exited))
    assert "max_token=" in exit_joined
    assert re.search(r"max_admin_token=.*Max-Age=0|max_admin_token=;\s*Max-Age=0", exit_joined)

    restore_admin = client.post("/api/auth/restore-session")
    assert restore_admin.status_code == 200
    assert restore_admin.json()["email"] == admin_email
