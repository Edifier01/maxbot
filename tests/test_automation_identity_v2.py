"""T11-C09: provider identity claims are global, durable and fail closed."""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
from unittest.mock import AsyncMock

import pytest

from app.tenant import tenant_scope


def _setup_server(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_DATA", str(tmp_path / "data"))
    import app.config as cfg
    import app.sqlite_backend as sqlite_backend

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    sqlite_backend.reset_connections()
    m.reset_test_runtime()
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()

    from app.tenant_init import ensure_tenant_data, init_global_db, init_tenant_db

    init_global_db(m)
    for tenant_id in (1, 2):
        ensure_tenant_data(m.ROOT, tenant_id)
        init_tenant_db(m, tenant_id)
    return m


def test_identity_claim_is_idempotent_and_same_profile_can_reauth() -> None:
    from app.repositories.automation_identity import AutomationIdentityRepository

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    repository = AutomationIdentityRepository(connection)

    repository.claim(tenant_id=1, profile_id=7, max_identity=101)
    repository.claim(tenant_id=1, profile_id=7, max_identity=101)
    repository.claim(tenant_id=1, profile_id=7, max_identity=202)
    row = connection.execute(
        "SELECT max_identity, tenant_id, profile_id FROM automation_identity_claims"
    ).fetchone()
    assert tuple(row) == ("202", 1, 7)


def test_identity_claim_conflict_does_not_disclose_existing_owner() -> None:
    from app.repositories.automation_identity import (
        AutomationIdentityConflict,
        AutomationIdentityRepository,
    )

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    repository = AutomationIdentityRepository(connection)
    repository.claim(tenant_id=1, profile_id=7, max_identity="max-user-1")

    with pytest.raises(AutomationIdentityConflict) as caught:
        repository.claim(tenant_id=2, profile_id=7, max_identity="max-user-1")
    assert str(caught.value) == "ACCOUNT_AUTOMATION_CONFLICT"
    assert "tenant" not in str(caught.value).lower()
    assert "profile" not in str(caught.value).lower()


def test_different_tenants_can_claim_different_provider_identities() -> None:
    from app.repositories.automation_identity import AutomationIdentityRepository

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    repository = AutomationIdentityRepository(connection)
    repository.claim(tenant_id=1, profile_id=7, max_identity=101)
    repository.claim(tenant_id=2, profile_id=7, max_identity=202)
    assert connection.execute(
        "SELECT COUNT(*) FROM automation_identity_claims"
    ).fetchone()[0] == 2


def test_release_removes_only_the_requested_tenant_profile_claim() -> None:
    from app.repositories.automation_identity import AutomationIdentityRepository

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    repository = AutomationIdentityRepository(connection)
    repository.claim(tenant_id=1, profile_id=7, max_identity=101)
    repository.claim(tenant_id=2, profile_id=7, max_identity=202)
    repository.release(tenant_id=1, profile_id=7)
    row = connection.execute(
        "SELECT max_identity, tenant_id, profile_id FROM automation_identity_claims"
    ).fetchone()
    assert tuple(row) == ("202", 2, 7)


def test_main_server_claim_is_tenant_scoped_and_fail_closed(monkeypatch) -> None:
    import main as m

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    monkeypatch.setattr(m, "_is_server_mode", lambda: True)
    monkeypatch.setattr(m, "_global_conn", lambda: connection)

    with tenant_scope(tenant_id=1, role="admin"):
        m._claim_automation_identity(7, 101)
    with tenant_scope(tenant_id=2, role="user"):
        with pytest.raises(RuntimeError) as caught:
            m._claim_automation_identity(7, 101)
    assert str(caught.value) == "ACCOUNT_AUTOMATION_CONFLICT"


def test_login_conflict_stays_needs_reauth_without_activating_profile(
    tmp_path, monkeypatch
) -> None:
    m = _setup_server(tmp_path, monkeypatch)
    from app.routes_profiles import login_profile

    with tenant_scope(tenant_id=2, role="user"):
        m._claim_automation_identity(9, 101)
    with tenant_scope(tenant_id=1, role="user"):
        with m._conn() as connection:
            connection.execute(
                "INSERT INTO profiles (id, phone, status) "
                "VALUES (7, '+79990007777', 'pending')"
            )

        monkeypatch.setattr(m, "_require_vault_unlocked", lambda: None)
        login = AsyncMock(return_value=101)
        monkeypatch.setattr(m, "_login_max", login)

        async def run_login() -> None:
            await login_profile(7)
            task = m._login_tasks[m._auth_session_key(7)]
            await task

        asyncio.run(run_login())

        with m._conn() as connection:
            profile = connection.execute(
                "SELECT status, last_error FROM profiles WHERE id=7"
            ).fetchone()
        assert profile["status"] == m.ProfileStatus.NEEDS_REAUTH
        assert profile["last_error"] == (
            "Аккаунт MAX уже используется в другой области автоматизации."
        )
        login.assert_awaited_once()

    with tenant_scope(use_global_data=True, role="admin"):
        with m._global_conn() as connection:
            claims = connection.execute(
                "SELECT tenant_id, profile_id, max_identity "
                "FROM automation_identity_claims"
            ).fetchall()
    assert [tuple(row) for row in claims] == [(2, 9, "101")]
