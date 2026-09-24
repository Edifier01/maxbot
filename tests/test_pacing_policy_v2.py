"""T13: role snapshots, deadlines, and business-date accounting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.pacing import (
    BudgetAuthorization,
    RoleSnapshot,
    business_date_utc3,
    effective_daily_target,
    evaluate_eligibility,
    fan_out_pacing_settings,
    materialize_role_snapshot,
    next_allowed_at,
)


UTC = timezone.utc


def test_effective_daily_target_preserves_active_quiet_skip_roles() -> None:
    assert effective_daily_target(5, role="active", quiet_limit=1) == 5
    assert effective_daily_target(5, role="quiet", quiet_limit=1) == 1
    assert effective_daily_target(5, role="skip", quiet_limit=1) == 0


def test_existing_role_snapshot_is_read_only_and_not_resampled() -> None:
    existing = RoleSnapshot(day="2026-09-20", role="quiet", sampled_limit=7, quiet_limit=2)
    assert materialize_role_snapshot(
        existing,
        day="2026-09-20",
        role="active",
        sampled_limit=99,
        quiet_limit=1,
    ) == existing


def test_next_allowed_at_uses_latest_server_deadline_without_24h_cap() -> None:
    now = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    server_deadline = now + timedelta(hours=48)
    assert next_allowed_at(
        now,
        configured_floor_seconds=180,
        generated_delay_seconds=30,
        server_deadline=server_deadline,
    ) == server_deadline


def test_floor_is_applied_after_short_random_branch() -> None:
    now = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    assert next_allowed_at(
        now,
        configured_floor_seconds=180,
        generated_delay_seconds=30,
    ) == now + timedelta(seconds=180)


def test_budget_date_is_frozen_before_midnight_and_ack_does_not_relabel_it() -> None:
    authorized_at = datetime(2026, 9, 20, 20, 59, tzinfo=UTC)
    acknowledged_at = datetime(2026, 9, 20, 21, 1, tzinfo=UTC)
    authorization = BudgetAuthorization.authorize(authorized_at)
    completed = authorization.acknowledge(acknowledged_at)
    assert authorization.budget_date == "2026-09-20"
    assert completed.budget_date == authorization.budget_date
    assert completed.acknowledged_at == acknowledged_at
    assert business_date_utc3(acknowledged_at) == "2026-09-21"


def test_server_deadline_across_business_midnight_still_blocks_until_expiry() -> None:
    before_deadline = datetime(2026, 9, 20, 20, 30, tzinfo=UTC)
    deadline = datetime(2026, 9, 20, 21, 30, tzinfo=UTC)
    waiting = evaluate_eligibility(
        now=before_deadline,
        role="active",
        sampled_limit=5,
        quiet_limit=1,
        sent_count=0,
        server_deadline=deadline,
    )
    assert waiting.allowed is False
    assert waiting.reason == "deadline"
    assert waiting.next_allowed_at == deadline

    after_deadline = evaluate_eligibility(
        now=datetime(2026, 9, 20, 22, 0, tzinfo=UTC),
        role="active",
        sampled_limit=5,
        quiet_limit=1,
        sent_count=0,
        server_deadline=deadline,
    )
    assert after_deadline.allowed is True


def test_eligibility_blocks_tenant_ban_but_proxy_failure_only_blocks_route() -> None:
    now = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    tenant_stop = evaluate_eligibility(
        now=now,
        role="active",
        sampled_limit=5,
        quiet_limit=1,
        sent_count=0,
        tenant_sanction="confirmed_ban",
    )
    route_stop = evaluate_eligibility(
        now=now,
        role="active",
        sampled_limit=5,
        quiet_limit=1,
        sent_count=0,
        route_ready=False,
    )
    assert tenant_stop.allowed is False
    assert tenant_stop.reason == "tenant_stopped"
    assert route_stop.allowed is False
    assert route_stop.reason == "route_unavailable"


def test_unclear_wait_requires_review_instead_of_guessing_scope() -> None:
    result = evaluate_eligibility(
        now=datetime(2026, 9, 20, 10, 0, tzinfo=UTC),
        role="active",
        sampled_limit=5,
        quiet_limit=1,
        sent_count=0,
        server_deadline=None,
        unclear_wait=True,
    )
    assert result.allowed is False
    assert result.reason == "review_required"


def test_global_fanout_filters_secrets_and_reports_partial_failures() -> None:
    calls: list[tuple[int, dict[str, str]]] = []

    def apply(tenant_id: int, values: dict[str, str]) -> None:
        if tenant_id == 2:
            raise RuntimeError("fixture failure")
        calls.append((tenant_id, values))

    report = fan_out_pacing_settings(
        {"daily_limit_min": 5, "auto_run": 1, "api_pin": "secret"},
        [1, 2],
        apply,
    )
    assert report.applied == [1]
    assert report.failed == [2]
    assert calls == [(1, {"daily_limit_min": "5"})]


def test_invalid_role_is_rejected() -> None:
    with pytest.raises(ValueError):
        effective_daily_target(5, role="other", quiet_limit=1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("sampled_limit", "quiet_limit"),
    [(-1, 1), (5, -1)],
)
def test_negative_limits_are_rejected(sampled_limit: int, quiet_limit: int) -> None:
    with pytest.raises(ValueError):
        effective_daily_target(
            sampled_limit, role="active", quiet_limit=quiet_limit
        )
