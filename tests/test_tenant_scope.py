"""P3-1: tenant_scope восстанавливает контекст."""

from __future__ import annotations

from app.tenant import (
    get_tenant_id,
    get_user_role,
    set_context,
    snapshot_context,
    tenant_scope,
)


def test_tenant_scope_restores_context():
    set_context(user_id=42, tenant_id=None, role="admin")
    assert get_tenant_id() is None
    assert get_user_role() == "admin"

    with tenant_scope(tenant_id=7, role="admin"):
        assert get_tenant_id() == 7

    assert get_tenant_id() is None
    assert get_user_role() == "admin"


def test_snapshot_roundtrip():
    set_context(user_id=1, tenant_id=2, role="user", impersonating=True)
    snap = snapshot_context()
    set_context(user_id=99, tenant_id=88, role="admin")
    from app.tenant import restore_context

    restore_context(snap)
    assert get_tenant_id() == 2
    assert get_user_role() == "user"
