"""Tenant path isolation (P0): ContextVar → data dir без globals."""

from __future__ import annotations

from app.tenant import clear_context, get_effective_data_dir, set_context


def test_effective_data_dir_switches_with_tenant_context(tmp_path):
    root = tmp_path

    set_context(tenant_id=1, role="user")
    assert get_effective_data_dir(root) == root / "data" / "tenants" / "1"

    set_context(tenant_id=2, role="user")
    assert get_effective_data_dir(root) == root / "data" / "tenants" / "2"

    set_context(use_global_data=True, role="admin")
    assert get_effective_data_dir(root) == root / "data" / "global"

    clear_context()
