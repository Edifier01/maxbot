"""E2E smoke: auth → admin → tenant isolation (httpx TestClient + PostgreSQL).

Requires DATABASE_URL. Skipped locally without PG; CI job server-e2e provides postgres service.
"""

from __future__ import annotations

import os
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
    admin_email = os.environ["ADMIN_EMAIL"]

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["db_ok"] is True
    assert health.json()["server_mode"] is True

    reg_a = client.post(
        "/api/auth/register",
        json={
            "institution_name": f"School A {uid}",
            "email": f"user-a-{uid}@example.com",
            "password": "UserPass123!",
            "password_confirm": "UserPass123!",
        },
    )
    assert reg_a.status_code == 200, reg_a.text
    body_a = reg_a.json()
    token_a = body_a["token"]
    tenant_a = body_a["tenant_id"]

    reg_b = client.post(
        "/api/auth/register",
        json={
            "institution_name": f"School B {uid}",
            "email": f"user-b-{uid}@example.com",
            "password": "UserPass123!",
            "password_confirm": "UserPass123!",
        },
    )
    assert reg_b.status_code == 200
    token_b = reg_b.json()["token"]
    tenant_b = reg_b.json()["tenant_id"]
    assert tenant_a != tenant_b

    me_a = client.get("/api/auth/me", headers=_bearer(token_a))
    assert me_a.status_code == 200
    assert me_a.json()["tenant_id"] == tenant_a
    assert me_a.json()["subscription"]["active"] is False

    dir_a = main_mod.ROOT / "data" / "tenants" / str(tenant_a) / "app.db"
    dir_b = main_mod.ROOT / "data" / "tenants" / str(tenant_b) / "app.db"
    assert dir_a.is_file()
    assert dir_b.is_file()

    admin_login = client.post(
        "/api/auth/login",
        json={"email": admin_email, "password": "AdminPass123!"},
    )
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["token"]

    users = client.get("/api/admin/users", headers=_bearer(admin_token))
    assert users.status_code == 200
    emails = {row["email"] for row in users.json()["items"]}
    assert f"user-a-{uid}@example.com" in emails
    assert f"user-b-{uid}@example.com" in emails

    profiles_as_admin = client.get("/api/profiles", headers=_bearer(admin_token))
    assert profiles_as_admin.status_code == 403

    grant = client.post(
        f"/api/admin/users/{tenant_a}/subscription",
        headers=_bearer(admin_token),
        json={"days": 30},
    )
    assert grant.status_code == 200

    me_a2 = client.get("/api/auth/me", headers=_bearer(token_a))
    assert me_a2.json()["subscription"]["active"] is True

    no_sub_campaign = client.post("/api/campaign/start", headers=_bearer(token_b))
    assert no_sub_campaign.status_code == 403
    assert "Подписка" in no_sub_campaign.json()["detail"]

    imp = client.post(
        f"/api/admin/impersonate/{tenant_a}",
        headers=_bearer(admin_token),
    )
    assert imp.status_code == 200
    imp_token = imp.json()["token"]

    status_imp = client.get("/api/status", headers=_bearer(imp_token))
    assert status_imp.status_code == 200

    deleted = client.delete(
        f"/api/admin/users/{tenant_b}",
        headers=_bearer(admin_token),
    )
    assert deleted.status_code == 200

    me_b = client.get("/api/auth/me", headers=_bearer(token_b))
    assert me_b.status_code == 401

    logout = client.post("/api/auth/logout", headers=_bearer(imp_token))
    assert logout.status_code == 200

    after_logout = client.get("/api/status", headers=_bearer(imp_token))
    assert after_logout.status_code == 401
