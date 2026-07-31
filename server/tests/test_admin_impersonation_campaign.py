"""Admin impersonation: /me email, campaign control, history APIs."""

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
def imp_client(tmp_path, monkeypatch):
    uid = uuid.uuid4().hex[:8]
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("JWT_SECRET", "imp-jwt-secret-min-32-characters-long")
    monkeypatch.setenv("ADMIN_EMAIL", f"admin-{uid}@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "AdminPass123!")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "imp-internal-token")

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


def test_impersonation_me_email_and_campaign_history(imp_client):
    client, _main, uid = imp_client
    user_email = f"tenant-{uid}@example.com"
    admin_email = os.environ["ADMIN_EMAIL"]

    reg = client.post(
        "/api/auth/register",
        json={
            "institution_name": f"School {uid}",
            "email": user_email,
            "password": "UserPass123!",
            "password_confirm": "UserPass123!",
        },
    )
    assert reg.status_code == 200, reg.text
    tenant_id = reg.json()["tenant_id"]

    admin_login = client.post(
        "/api/auth/login",
        json={"email": admin_email, "password": "AdminPass123!"},
    )
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["token"]

    client.post(
        f"/api/admin/users/{tenant_id}/subscription",
        headers=_bearer(admin_token),
        json={"days": 30},
    )

    imp = client.post(
        f"/api/admin/impersonate/{tenant_id}",
        headers=_bearer(admin_token),
    )
    assert imp.status_code == 200
    imp_token = imp.json()["token"]

    me = client.get("/api/auth/me", headers=_bearer(imp_token))
    assert me.status_code == 200
    body = me.json()
    assert body["impersonating"] is True
    assert body["email"] == user_email
    assert body["actor_email"] == admin_email

    admin_me = client.get("/api/auth/me", headers=_bearer(admin_token))
    assert admin_me.json()["email"] == admin_email
    assert "actor_email" not in admin_me.json()

    status = client.get("/api/status", headers=_bearer(imp_token))
    assert status.status_code == 200
    assert "log" in status.json()

    campaigns = client.get("/api/campaigns?limit=10", headers=_bearer(imp_token))
    assert campaigns.status_code == 200
    assert "items" in campaigns.json()

    send_log = client.get("/api/send_log?limit=10", headers=_bearer(imp_token))
    assert send_log.status_code == 200
    assert "items" in send_log.json()

    stop = client.post("/api/campaign/stop", headers=_bearer(imp_token))
    assert stop.status_code == 200
    assert stop.json()["ok"] is True

    start = client.post("/api/campaign/start", headers=_bearer(imp_token))
    assert start.status_code == 400
    assert start.status_code != 403
    detail = start.json()["detail"]
    assert "сообщен" in detail.lower() or "групп" in detail.lower() or "профил" in detail.lower()
