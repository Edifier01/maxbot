"""E2E smoke: auth → admin → tenant isolation (httpx TestClient + PostgreSQL).

Requires DATABASE_URL. Skipped locally without PG; CI job server-e2e provides postgres service.
"""

from __future__ import annotations

import os
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


def _admin_token(client) -> str:
    response = client.post(
        "/api/auth/login",
        json={"email": os.environ["ADMIN_EMAIL"], "password": "AdminPass123!"},
    )
    assert response.status_code == 200, response.text
    return _cookie_token(response)


def _create_user(
    client, admin_token: str, institution_name: str, email: str
) -> tuple[int, str]:
    response = client.post(
        "/api/admin/users",
        cookies=_tok(admin_token),
        json={
            "institution_name": institution_name,
            "login": email,
            "password": "UserPass123!",
        },
    )
    assert response.status_code == 200, response.text
    login = client.post(
        "/api/auth/login", json={"email": email, "password": "UserPass123!"}
    )
    assert login.status_code == 200, login.text
    return response.json()["tenant_id"], _cookie_token(login)


@pytest.fixture
def e2e_client(tmp_path, monkeypatch):
    uid = uuid.uuid4().hex[:8]
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("JWT_SECRET", "e2e-jwt-secret-min-32-characters-long")
    monkeypatch.setenv("ADMIN_EMAIL", f"admin-{uid}@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "AdminPass123!")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "e2e-internal-token")

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
        yield client, m, uid

    db_pg.close()


def test_e2e_auth_admin_tenant_flow(e2e_client):
    client, main_mod, uid = e2e_client

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["db_ok"] is True
    assert health.json()["server_mode"] is True

    admin_token = _admin_token(client)
    tenant_a, token_a = _create_user(
        client, admin_token, f"School A {uid}", f"user-a-{uid}@example.com"
    )
    tenant_b, token_b = _create_user(
        client, admin_token, f"School B {uid}", f"user-b-{uid}@example.com"
    )
    assert tenant_a != tenant_b

    me_a = client.get("/api/auth/me", cookies=_tok(token_a))
    assert me_a.status_code == 200
    assert me_a.json()["tenant_id"] == tenant_a
    assert me_a.json()["subscription"]["active"] is False
    assert me_a.json()["subscription"]["expires_at"] is None

    dir_a = main_mod.ROOT / "data" / "tenants" / str(tenant_a) / "app.db"
    dir_b = main_mod.ROOT / "data" / "tenants" / str(tenant_b) / "app.db"
    assert dir_a.is_file()
    assert dir_b.is_file()

    users = client.get("/api/admin/users", cookies=_tok(admin_token))
    assert users.status_code == 200
    emails = {row["email"] for row in users.json()["items"]}
    assert f"user-a-{uid}@example.com" in emails
    assert f"user-b-{uid}@example.com" in emails

    profiles_as_admin = client.get("/api/profiles", cookies=_tok(admin_token))
    assert profiles_as_admin.status_code == 403

    grant = client.post(
        f"/api/admin/users/{tenant_a}/subscription",
        cookies=_tok(admin_token),
        json={"days": 30},
    )
    assert grant.status_code == 200

    me_a2 = client.get("/api/auth/me", cookies=_tok(token_a))
    assert me_a2.json()["subscription"]["active"] is True

    no_sub_campaign = client.post("/api/campaign/start", cookies=_tok(token_b))
    assert no_sub_campaign.status_code == 403
    assert "Подписка" in no_sub_campaign.json()["detail"]

    imp = client.post(
        f"/api/admin/impersonate/{tenant_a}",
        cookies=_tok(admin_token),
    )
    assert imp.status_code == 200
    imp_token = _cookie_token(imp)

    status_imp = client.get("/api/status", cookies=_tok(imp_token))
    assert status_imp.status_code == 200

    deleted = client.delete(
        f"/api/admin/users/{tenant_b}",
        cookies=_tok(admin_token),
    )
    assert deleted.status_code == 200
    assert deleted.json().get("ok") is True

    tenant_b_dir = main_mod.ROOT / "data" / "tenants" / str(tenant_b)
    assert not tenant_b_dir.exists()

    from app import db_pg

    assert db_pg.get_tenant(tenant_b) is None
    assert db_pg.get_user_by_email(f"user-b-{uid}@example.com") is None

    users_after = client.get("/api/admin/users", cookies=_tok(admin_token))
    assert users_after.status_code == 200
    emails_after = {row["email"] for row in users_after.json()["items"]}
    assert f"user-b-{uid}@example.com" not in emails_after

    me_b = client.get("/api/auth/me", cookies=_tok(token_b))
    assert me_b.status_code == 401

    logout = client.post("/api/auth/logout", cookies=_tok(imp_token))
    assert logout.status_code == 200

    after_logout = client.get("/api/status", cookies=_tok(imp_token))
    assert after_logout.status_code == 401


def test_tenant_token_bump_revokes_session(e2e_client):
    """bump_tenant_token_version invalidates outstanding JWT (tv mismatch)."""
    client, _main_mod, uid = e2e_client

    tenant_id, token = _create_user(
        client, _admin_token(client), f"Revoke Test {uid}", f"revoke-{uid}@example.com"
    )

    me_ok = client.get("/api/auth/me", cookies=_tok(token))
    assert me_ok.status_code == 200

    from app import auth, db_pg

    db_pg.bump_tenant_token_version(tenant_id)
    auth.clear_session_cache()

    me_revoked = client.get("/api/auth/me", cookies=_tok(token))
    assert me_revoked.status_code == 401
    assert "отозвана" in me_revoked.json()["detail"].lower()


def test_admin_tenant_worker_pool_settings(e2e_client):
    client, _main_mod, uid = e2e_client
    admin_token = _admin_token(client)
    tenant_id, token_user = _create_user(
        client, admin_token, f"Worker Pool School {uid}", f"wp-{uid}@example.com"
    )

    default_settings = client.get(
        f"/api/admin/tenants/{tenant_id}/settings",
        cookies=_tok(admin_token),
    )
    assert default_settings.status_code == 200
    assert default_settings.json()["worker_pool_size"] == 1

    set_pool = client.put(
        f"/api/admin/tenants/{tenant_id}/settings",
        cookies=_tok(admin_token),
        json={"worker_pool_size": 4},
    )
    assert set_pool.status_code == 200, set_pool.text
    body = set_pool.json()
    assert body["ok"] is True
    assert body["worker_pool_size"] == 4
    assert body["worker_restarted"] is False

    updated = client.get(
        f"/api/admin/tenants/{tenant_id}/settings",
        cookies=_tok(admin_token),
    )
    assert updated.status_code == 200
    assert updated.json()["worker_pool_size"] == 4

    user_settings = client.get("/api/settings", cookies=_tok(token_user))
    assert user_settings.status_code == 403

    blocked = client.put(
        "/api/settings",
        cookies=_tok(token_user),
        json={"worker_pool_size": 8},
    )
    assert blocked.status_code == 403

    still_four = client.get(
        f"/api/admin/tenants/{tenant_id}/settings",
        cookies=_tok(admin_token),
    )
    assert still_four.status_code == 200
    assert still_four.json()["worker_pool_size"] == 4

    out_of_range = client.put(
        f"/api/admin/tenants/{tenant_id}/settings",
        cookies=_tok(admin_token),
        json={"worker_pool_size": 64},
    )
    assert out_of_range.status_code == 422


def test_admin_subscription_extend_and_revoke(e2e_client):
    from datetime import datetime, timedelta, timezone

    client, _main_mod, uid = e2e_client
    admin_token = _admin_token(client)
    tenant_id, token_user = _create_user(
        client, admin_token, f"Sub School {uid}", f"sub-{uid}@example.com"
    )

    me0 = client.get("/api/auth/me", cookies=_tok(token_user))
    assert me0.json()["subscription"] == {"active": False, "expires_at": None}

    missing = client.post(
        "/api/admin/users/999999/subscription/revoke",
        cookies=_tok(admin_token),
    )
    assert missing.status_code == 404

    first = client.post(
        f"/api/admin/users/{tenant_id}/subscription",
        cookies=_tok(admin_token),
        json={"days": 5},
    )
    assert first.status_code == 200
    exp1 = datetime.fromisoformat(first.json()["expires_at"])

    second = client.post(
        f"/api/admin/users/{tenant_id}/subscription/month",
        cookies=_tok(admin_token),
    )
    assert second.status_code == 200
    exp2 = datetime.fromisoformat(second.json()["expires_at"])
    assert exp2 - exp1 >= timedelta(days=29, hours=23)
    assert exp2 - datetime.now(timezone.utc) > timedelta(days=30)

    me_active = client.get("/api/auth/me", cookies=_tok(token_user))
    assert me_active.json()["subscription"]["active"] is True

    revoked = client.post(
        f"/api/admin/users/{tenant_id}/subscription/revoke",
        cookies=_tok(admin_token),
    )
    assert revoked.status_code == 200
    assert revoked.json()["ok"] is True
    assert revoked.json()["active"] is False
    assert revoked.json()["expires_at"] is not None

    me_revoked = client.get("/api/auth/me", cookies=_tok(token_user))
    sub = me_revoked.json()["subscription"]
    assert sub["active"] is False
    assert sub["expires_at"] is not None

    blocked = client.post("/api/campaign/start", cookies=_tok(token_user))
    assert blocked.status_code == 403
    assert "Подписка" in blocked.json()["detail"]

