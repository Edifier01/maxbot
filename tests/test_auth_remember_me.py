"""Remember-me persistent login: HttpOnly cookie + restore-session."""

from __future__ import annotations

import os
import re
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL required (PostgreSQL)",
)


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


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


def _register_user(client, uid: str, *, remember_me: bool = True):
    return client.post(
        "/api/auth/register",
        json={
            "institution_name": f"School {uid}",
            "email": f"user-{uid}@example.com",
            "password": "UserPass123!",
            "password_confirm": "UserPass123!",
            "remember_me": remember_me,
        },
    )


def test_login_remember_me_sets_httponly_cookie(auth_client):
    client, uid = auth_client
    reg = _register_user(client, uid)
    assert reg.status_code == 200

    login = client.post(
        "/api/auth/login",
        json={
            "email": f"user-{uid}@example.com",
            "password": "UserPass123!",
            "remember_me": True,
        },
    )
    assert login.status_code == 200
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
            "email": f"user-{uid}@example.com",
            "password": "UserPass123!",
            "remember_me": False,
        },
    )
    assert login.status_code == 200
    set_cookie = login.headers.get("set-cookie", "")
    assert "max_token=" not in set_cookie


def test_restore_session_with_valid_cookie(auth_client):
    client, uid = auth_client
    _register_user(client, uid)

    login = client.post(
        "/api/auth/login",
        json={
            "email": f"user-{uid}@example.com",
            "password": "UserPass123!",
            "remember_me": True,
        },
    )
    assert login.status_code == 200
    token = login.json()["token"]

    restore = client.post("/api/auth/restore-session")
    assert restore.status_code == 200
    body = restore.json()
    assert body["token"] == token
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
            "email": f"user-{uid}@example.com",
            "password": "UserPass123!",
            "remember_me": True,
        },
    )
    assert login.status_code == 200
    token = login.json()["token"]
    assert "max_token=" in login.headers.get("set-cookie", "")

    logout = client.post("/api/auth/logout", headers=_bearer(token))
    assert logout.status_code == 200
    set_cookie = logout.headers.get("set-cookie", "")
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
        json={"email": admin_email, "password": "AdminPass123!", "remember_me": True},
    )
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["token"]

    imp = client.post(
        f"/api/admin/impersonate/{tenant_id}",
        headers=_bearer(admin_token),
    )
    assert imp.status_code == 200
    set_cookie = imp.headers.get("set-cookie", "")
    assert "max_token=" not in set_cookie
