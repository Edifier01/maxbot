"""db_pg helpers from Agent Review Round 3."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from conftest import requires_postgres as _PG

from app import db_pg


def test_extend_subscription_locks_tenant_row_before_history(monkeypatch):
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    current = now + timedelta(days=5)
    expected = now + timedelta(days=35)
    tenant_id = 7
    admin_id = 11
    cur = MagicMock()
    cur.fetchall.return_value = [{"expires_at": current}]
    ctx = MagicMock()
    ctx.__enter__.return_value = cur
    ctx.__exit__.return_value = False
    cursor_factory = MagicMock(return_value=ctx)
    monkeypatch.setattr(db_pg, "_cursor", cursor_factory)
    monkeypatch.setattr(db_pg, "_now", lambda: now)

    assert db_pg.extend_subscription(tenant_id, 30, admin_id) == expected

    cursor_factory.assert_called_once_with(transaction=True)
    statements = [" ".join(call.args[0].split()) for call in cur.execute.call_args_list]
    assert statements == [
        "SELECT id FROM tenants WHERE id = %s FOR UPDATE",
        "SELECT expires_at FROM subscriptions WHERE tenant_id = %s FOR UPDATE",
        "INSERT INTO subscriptions (tenant_id, expires_at, granted_by) "
        "VALUES (%s, %s, %s)",
    ]
    assert [call.args[1] for call in cur.execute.call_args_list] == [
        (tenant_id,),
        (tenant_id,),
        (tenant_id, expected, admin_id),
    ]


def test_subscription_info_from_expires_active():
    exp = datetime.now(timezone.utc) + timedelta(days=30)
    info = db_pg.subscription_info_from_expires(exp)
    assert info["active"] is True
    assert info["expires_at"] == exp.isoformat()


def test_subscription_info_from_expires_expired():
    exp = datetime.now(timezone.utc) - timedelta(days=1)
    info = db_pg.subscription_info_from_expires(exp)
    assert info["active"] is False
    assert info["expires_at"] == exp.isoformat()


def test_subscription_info_from_expires_none():
    assert db_pg.subscription_info_from_expires(None) == {
        "active": False,
        "expires_at": None,
    }


def _seed_tenant_admin() -> tuple[int, int]:
    db_pg.init_schema()
    tenant_id = db_pg.create_tenant("Sub helper test")
    db_pg.create_user(
        f"user-sub-{tenant_id}@example.com",
        "hash",
        tenant_id=tenant_id,
        role="user",
    )
    admin_id = db_pg.create_user(
        f"admin-sub-{tenant_id}@example.com",
        "hash",
        tenant_id=None,
        role="admin",
    )
    return tenant_id, admin_id


@_PG
def test_subscription_info_never_granted_is_null():
    tenant_id, _admin_id = _seed_tenant_admin()
    info = db_pg.subscription_info(tenant_id)
    assert info == {"active": False, "expires_at": None}


@_PG
def test_extend_subscription_from_remaining():
    tenant_id, admin_id = _seed_tenant_admin()
    now = datetime.now(timezone.utc)
    db_pg.grant_subscription(tenant_id, now + timedelta(days=5), admin_id)
    new_exp = db_pg.extend_subscription(tenant_id, 30, admin_id)
    expected = now + timedelta(days=35)
    assert abs((new_exp - expected).total_seconds()) < 3
    assert db_pg.subscription_active(tenant_id) is True
    info = db_pg.subscription_info(tenant_id)
    assert info["active"] is True
    assert info["expires_at"] is not None


@_PG
def test_extend_subscription_adds_to_long_remaining():
    tenant_id, admin_id = _seed_tenant_admin()
    now = datetime.now(timezone.utc)
    db_pg.grant_subscription(tenant_id, now + timedelta(days=60), admin_id)
    new_exp = db_pg.extend_subscription(tenant_id, 30, admin_id)
    expected = now + timedelta(days=90)
    assert abs((new_exp - expected).total_seconds()) < 3


@_PG
def test_extend_subscription_from_expired_starts_now():
    tenant_id, admin_id = _seed_tenant_admin()
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=3)
    db_pg.grant_subscription(tenant_id, past, admin_id)
    info = db_pg.subscription_info(tenant_id)
    assert info["active"] is False
    assert info["expires_at"] is not None
    new_exp = db_pg.extend_subscription(tenant_id, 30, admin_id)
    expected = now + timedelta(days=30)
    assert abs((new_exp - expected).total_seconds()) < 3
    assert db_pg.subscription_active(tenant_id) is True


@_PG
def test_revoke_subscription_deactivates():
    tenant_id, admin_id = _seed_tenant_admin()
    now = datetime.now(timezone.utc)
    db_pg.grant_subscription(tenant_id, now + timedelta(days=60), admin_id)
    revoked_at = db_pg.revoke_subscription(tenant_id, admin_id)
    assert db_pg.subscription_active(tenant_id) is False
    info = db_pg.subscription_info(tenant_id)
    assert info["active"] is False
    assert info["expires_at"] is not None
    assert abs((revoked_at - now).total_seconds()) < 3
    assert all(
        int(row["tenant_id"]) != tenant_id
        for row in db_pg.list_expiring_subscriptions(within_days=90)
    )
    assert any(
        int(row["tenant_id"]) == tenant_id
        for row in db_pg.tenants_recently_expired(since_hours=24)
    )
