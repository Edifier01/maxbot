"""T02: MAX_DATA is a base root and scopes never share tenant storage."""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
from pathlib import Path

import pytest


def test_scope_resolver_separates_global_and_tenants(tmp_path: Path) -> None:
    from app.domain.contracts import Scope, resolve_data_root, resolve_scope_dir

    root = resolve_data_root({"MAX_DATA": str(tmp_path / "base")})
    assert root == tmp_path / "base"
    assert resolve_scope_dir(root, Scope.GLOBAL) == root / "global"
    assert resolve_scope_dir(root, Scope.TENANT, tenant_id=1) == root / "tenants" / "1"
    assert resolve_scope_dir(root, Scope.TENANT, tenant_id=2) == root / "tenants" / "2"


def test_server_max_data_is_base_for_each_tenant(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_DATA", str(tmp_path / "base"))

    import app.config as cfg
    import main as m
    from app.tenant import tenant_scope

    importlib.reload(cfg)
    importlib.reload(m)
    m.reset_test_runtime()
    monkeypatch.setattr(m, "ROOT", tmp_path / "application")
    m._refresh_data_paths()

    with tenant_scope(tenant_id=1, role="user"):
        tenant_one = m._resolve_data_dir()
    with tenant_scope(tenant_id=2, role="user"):
        tenant_two = m._resolve_data_dir()

    assert tenant_one == tmp_path / "base" / "tenants" / "1"
    assert tenant_two == tmp_path / "base" / "tenants" / "2"
    assert tenant_one != tenant_two


def test_ambiguous_legacy_scope_is_reported_without_distribution(tmp_path) -> None:
    from app.domain.contracts import Scope, legacy_scope_manifest

    legacy = tmp_path / "shared" / "app.db"
    legacy.parent.mkdir()
    legacy.write_bytes(b"fixture")
    manifest = legacy_scope_manifest(tmp_path / "shared", Scope.TENANT, tenant_id=1)
    assert manifest["status"] == "BLOCKED"
    assert manifest["reason"] == "ambiguous_legacy_scope"
    assert legacy.is_file()


def test_max_data_scopes_keep_api_worker_cache_vault_backup_and_cleanup_separate(
    tmp_path, monkeypatch
) -> None:
    """AUD20-A23: identical local IDs stay isolated across runtime boundaries."""
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_DATA", str(tmp_path / "base"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MAX_USE_DATABASE_URL", raising=False)

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path / "application")
    m.reset_test_runtime()

    from app import auth_rate_limit
    from app.campaign_runtime import REGISTRY
    from app.campaign_worker import begin_campaign, finish_campaign
    from app.routes_dashboard import api_backup_now, api_list_backups, get_log
    from app.tenant import tenant_scope
    from app.tenant_init import (
        ensure_tenant_data,
        reconcile_tenant_quarantines,
    )

    local_profile_id = 7
    campaign_ids: dict[int, int] = {}
    backup_files: dict[int, str] = {}
    for tenant_id in (1, 2):
        with tenant_scope(tenant_id=tenant_id, role="user"):
            m._refresh_data_paths()
            ensure_tenant_data(m.ROOT, tenant_id)
            m.init_db()
            m.append_log(f"TENANT-{tenant_id}-ONLY")
            campaign_ids[tenant_id] = begin_campaign()

            # The API and backup implementation must resolve the current
            # tenant scope inside the async executor, not use a stale global.
            backup = asyncio.run(api_backup_now())
            backup_files[tenant_id] = backup["file"]
            listed = asyncio.run(api_list_backups())
            assert [row["file"] for row in listed["items"]] == [backup["file"]]
            log = asyncio.run(get_log())
            assert any(
                f"TENANT-{tenant_id}-ONLY" in line for line in log["lines"]
            )
            assert not any(
                f"TENANT-{3 - tenant_id}-ONLY" in line for line in log["lines"]
            )

            # Both tenants deliberately use the same local profile ID; vault
            # keys and session directories must still remain tenant-bound.
            m._ensure_vault_unlocked()
            session = m._session_dir(local_profile_id)
            session.mkdir(parents=True, exist_ok=True)
            plaintext = f"tenant-{tenant_id}-session".encode("ascii")
            (session / "session.db").write_bytes(plaintext)
            m._encrypt_session(local_profile_id)
            encrypted = (session / "session.db.enc").read_bytes()
            assert m._get_fernet().decrypt(encrypted) == plaintext

            runtime = REGISTRY.worker()
            runtime.worker_last_activity = float(tenant_id)
            assert runtime.tenant_id == tenant_id

            key = auth_rate_limit.user_rate_limit_key(
                local_profile_id, tenant_id, bucket=tenant_id
            )
            assert auth_rate_limit.check_auth_rate_limit(key, limit=1, window=60)
            assert not auth_rate_limit.check_auth_rate_limit(key, limit=1, window=60)

            finish_campaign("stopped", "scope-fixture")

    base = tmp_path / "base"
    tenant_one = base / "tenants" / "1"
    tenant_two = base / "tenants" / "2"
    assert tenant_one != tenant_two
    assert (tenant_one / "backups" / backup_files[1]).is_file()
    assert (tenant_two / "backups" / backup_files[2]).is_file()
    # Timestamp filenames may coincide; the containing scope and snapshot
    # contents, rather than a global filename, are the isolation boundary.
    with sqlite3.connect(tenant_one / "backups" / backup_files[1]) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM app_log WHERE msg LIKE '%TENANT-1-ONLY'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM app_log WHERE msg LIKE '%TENANT-2-ONLY'"
        ).fetchone()[0] == 0
    with sqlite3.connect(tenant_two / "backups" / backup_files[2]) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM app_log WHERE msg LIKE '%TENANT-2-ONLY'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM app_log WHERE msg LIKE '%TENANT-1-ONLY'"
        ).fetchone()[0] == 0

    with sqlite3.connect(tenant_one / "app.db") as connection:
        assert connection.execute(
            "SELECT status FROM campaigns WHERE id=?", (campaign_ids[1],)
        ).fetchone()[0] == "stopped"
        assert connection.execute(
            "SELECT msg FROM app_log WHERE msg=?", ("TENANT-2-ONLY",)
        ).fetchone() is None
    with sqlite3.connect(tenant_two / "app.db") as connection:
        assert connection.execute(
            "SELECT status FROM campaigns WHERE id=?", (campaign_ids[2],)
        ).fetchone()[0] == "stopped"
        assert connection.execute(
            "SELECT msg FROM app_log WHERE msg=?", ("TENANT-1-ONLY",)
        ).fetchone() is None

    assert auth_rate_limit.clear_tenant_rate_limit_keys(1, user_id=local_profile_id) >= 1
    key_two = auth_rate_limit.user_rate_limit_key(
        local_profile_id, 2, bucket=2
    )
    assert not auth_rate_limit.check_auth_rate_limit(key_two, limit=1, window=60)

    deleting_one = base / "tenants" / "3.deleting"
    deleting_two = base / "tenants" / "4.deleting"
    deleting_one.mkdir()
    deleting_two.mkdir()
    (deleting_one / "marker").write_text("one", encoding="utf-8")
    (deleting_two / "marker").write_text("two", encoding="utf-8")
    cleanup = reconcile_tenant_quarantines(base, lambda tenant_id: tenant_id == 3)
    assert cleanup == {"restored": 1, "purged": 1, "conflicts": 0}
    assert (base / "tenants" / "3" / "marker").read_text(encoding="utf-8") == "one"
    assert not deleting_two.exists()
    m.reset_test_runtime()
