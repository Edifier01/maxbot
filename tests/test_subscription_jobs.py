from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app import db_pg, subscription_jobs


def test_renewed_tenant_is_stopped_after_later_expiry(monkeypatch):
    tenant_id = 41
    expired_row = {
        "tenant_id": tenant_id,
        "institution_name": "Test School",
        "email": "admin@example.com",
        "expired_at": datetime(2026, 8, 25, tzinfo=timezone.utc),
    }
    active_states = iter((True, False))
    expired_rows = iter(([], [expired_row]))
    notifications = []
    stop_worker = AsyncMock()

    subscription_jobs.reset_for_tests()
    subscription_jobs._stopped_expired.add(tenant_id)
    monkeypatch.setattr(db_pg, "cleanup_revoked_tokens", lambda: 0)
    monkeypatch.setattr(
        db_pg, "list_expiring_subscriptions", lambda *, within_days: []
    )
    monkeypatch.setattr(
        db_pg,
        "tenants_recently_expired",
        lambda *, since_hours: next(expired_rows),
    )
    monkeypatch.setattr(
        db_pg, "subscription_active", lambda tid: next(active_states)
    )
    monkeypatch.setattr(subscription_jobs, "_stop_tenant_worker", stop_worker)
    monkeypatch.setattr(
        subscription_jobs,
        "_main",
        lambda: SimpleNamespace(
            _schedule_telegram=lambda title, lines, *, dedupe_key: notifications.append(
                (title, lines, dedupe_key)
            )
        ),
    )

    try:
        asyncio.run(subscription_jobs._tick())
        assert tenant_id not in subscription_jobs._stopped_expired

        asyncio.run(subscription_jobs._tick())
        stop_worker.assert_awaited_once_with(tenant_id, expired_row)
        assert tenant_id in subscription_jobs._stopped_expired
    finally:
        subscription_jobs.reset_for_tests()
