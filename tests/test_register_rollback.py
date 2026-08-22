"""Register rollback when init_tenant_db fails."""

from __future__ import annotations

import uuid
from unittest.mock import patch

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


@pytest.fixture
def reg_client(tmp_path, monkeypatch):
    uid = uuid.uuid4().hex[:8]
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("JWT_SECRET", "rollback-jwt-secret-min-32-chars")
    monkeypatch.setenv("ADMIN_EMAIL", f"admin-{uid}@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "AdminPass123!")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "rollback-internal-token")

    import importlib

    import app.config as cfg

    importlib.reload(cfg)

    import main as m

    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()

    from app import db_pg
    from app.hooks import before_start
    from app.auth_rate_limit import reset_for_tests

    reset_for_tests()
    _truncate_saas()
    before_start()
    m.reset_test_runtime()

    from starlette.testclient import TestClient

    with TestClient(m.app) as client:
        yield client, m, uid

    db_pg.close()


def test_admin_create_rollback_on_init_failure(reg_client):
    client, main_mod, uid = reg_client
    email = f"fail-{uid}@example.com"

    admin = client.post(
        "/api/auth/login",
        json={"login": f"admin-{uid}@example.com", "password": "AdminPass123!"},
    )
    assert admin.status_code == 200, admin.text

    with patch("app.tenant_init.init_tenant_db", side_effect=RuntimeError("boom")):
        r = client.post(
            "/api/admin/users",
            cookies={"max_token": admin.cookies.get("max_token")},
            json={
                "institution_name": "Test Org",
                "login": email,
                "password": "Password123!",
            },
        )
    assert r.status_code == 500

    from app import db_pg

    with db_pg._cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE email = %s", (email.lower(),))
        assert cur.fetchone() is None
        cur.execute("SELECT 1 FROM tenants WHERE institution_name = %s", ("Test Org",))
        assert cur.fetchone() is None

    data_dir = main_mod.ROOT / "data" / "tenants"
    if data_dir.is_dir():
        assert not any(data_dir.iterdir())
