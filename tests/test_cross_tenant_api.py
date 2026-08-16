"""Cross-tenant API isolation (requires PostgreSQL)."""

from __future__ import annotations

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


def _register(client, uid: str, n: int) -> tuple[dict, str]:
    email = f"user{n}-{uid}@example.com"
    body = {
        "institution_name": f"Org {n} {uid}",
        "email": email,
        "password": "CrossTestPass123!",
        "password_confirm": "CrossTestPass123!",
    }
    r = client.post("/api/auth/register", json=body)
    assert r.status_code == 200, r.text
    token = r.cookies.get("max_token")
    assert token
    return r.json(), token


@pytest.fixture
def cross_client(tmp_path, monkeypatch):
    uid = uuid.uuid4().hex[:8]
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("REGISTRATION_OPEN", "1")
    monkeypatch.setenv("JWT_SECRET", "cross-tenant-jwt-secret-min-32-chars")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "cross-internal-token")

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


def test_tenant_profiles_isolated(cross_client):
    client, uid = cross_client
    a, token_a = _register(client, uid, 1)
    b, token_b = _register(client, uid, 2)

    cookies_a = {"max_token": token_a}
    cookies_b = {"max_token": token_b}

    ra = client.get("/api/profiles", cookies=cookies_a)
    rb = client.get("/api/profiles", cookies=cookies_b)
    assert ra.status_code == 200
    assert rb.status_code == 200
    assert ra.json().get("items") == []
    assert rb.json().get("items") == []

    import main as m

    dir_a = m.ROOT / "data" / "tenants" / str(a["tenant_id"])
    dir_b = m.ROOT / "data" / "tenants" / str(b["tenant_id"])
    assert dir_a.is_dir()
    assert dir_b.is_dir()
    assert dir_a != dir_b

    r_admin = client.get("/api/admin/users", cookies=cookies_b)
    assert r_admin.status_code == 403

    delete_other = client.delete(
        f"/api/admin/users/{a['tenant_id']}",
        cookies=cookies_b,
    )
    assert delete_other.status_code == 403

    settings_other = client.get(
        f"/api/admin/tenants/{a['tenant_id']}/settings",
        cookies=cookies_b,
    )
    assert settings_other.status_code == 403

    settings_put_other = client.put(
        f"/api/admin/tenants/{a['tenant_id']}/settings",
        cookies=cookies_b,
        json={"worker_pool_size": 2},
    )
    assert settings_put_other.status_code == 403


def test_two_tenants_independent_worker_runtime(cross_client):
    client, uid = cross_client
    a, _ = _register(client, uid, 1)
    b, _ = _register(client, uid, 2)

    from app.campaign_runtime import REGISTRY

    REGISTRY.reset_test()
    rt_a = REGISTRY.worker_for(a["tenant_id"])
    rt_b = REGISTRY.worker_for(b["tenant_id"])
    assert rt_a is not rt_b
    rt_a.worker_last_activity = 42.0
    assert rt_b.worker_last_activity == 0.0
