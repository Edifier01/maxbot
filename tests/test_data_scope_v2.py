"""T02: MAX_DATA is a base root and scopes never share tenant storage."""

from __future__ import annotations

import importlib
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
