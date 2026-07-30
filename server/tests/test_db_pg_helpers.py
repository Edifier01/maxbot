"""db_pg helpers from Agent Review Round 3."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import db_pg


def test_subscription_info_from_expires_active():
    exp = datetime.now(timezone.utc) + timedelta(days=30)
    info = db_pg.subscription_info_from_expires(exp)
    assert info["active"] is True
    assert info["expires_at"] is not None


def test_subscription_info_from_expires_expired():
    exp = datetime.now(timezone.utc) - timedelta(days=1)
    info = db_pg.subscription_info_from_expires(exp)
    assert info["active"] is False
    assert info["expires_at"] is None


def test_subscription_info_from_expires_none():
    assert db_pg.subscription_info_from_expires(None) == {
        "active": False,
        "expires_at": None,
    }
