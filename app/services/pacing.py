"""Pure policy primitives for roles, deadlines, and budget authorization."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from app.settings_scope import filter_pacing_updates


Role = Literal["active", "quiet", "skip"]
BUSINESS_TIMEZONE = timezone(timedelta(hours=3))


def _validated_role(role: str) -> Role:
    if role not in {"active", "quiet", "skip"}:
        raise ValueError(f"unsupported role: {role}")
    return role  # type: ignore[return-value]


def effective_daily_target(
    sampled_limit: int, *, role: str, quiet_limit: int
) -> int:
    """Return the already-sampled target without introducing a new cap."""

    if int(sampled_limit) < 0 or int(quiet_limit) < 0:
        raise ValueError("limits must not be negative")
    checked_role = _validated_role(role)
    sampled = int(sampled_limit)
    quiet = int(quiet_limit)
    if checked_role == "skip":
        return 0
    if checked_role == "quiet":
        return min(sampled, quiet)
    return sampled


@dataclass(frozen=True)
class RoleSnapshot:
    day: str
    role: Role
    sampled_limit: int
    quiet_limit: int

    @property
    def target(self) -> int:
        return effective_daily_target(
            self.sampled_limit, role=self.role, quiet_limit=self.quiet_limit
        )


def materialize_role_snapshot(
    existing: RoleSnapshot | None,
    *,
    day: str,
    role: str,
    sampled_limit: int,
    quiet_limit: int,
) -> RoleSnapshot:
    """Create once at the approved boundary; reads never resample or rewrite."""

    if existing is not None:
        return existing
    checked_role = _validated_role(role)
    return RoleSnapshot(
        day=str(day),
        role=checked_role,
        sampled_limit=max(0, int(sampled_limit)),
        quiet_limit=max(0, int(quiet_limit)),
    )


def business_date_utc3(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(BUSINESS_TIMEZONE).date().isoformat()


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def next_allowed_at(
    now: datetime,
    *,
    configured_floor_seconds: float = 0.0,
    generated_delay_seconds: float = 0.0,
    server_deadline: datetime | None = None,
    persisted_deadline: datetime | None = None,
) -> datetime | None:
    """Take the latest applicable deadline; never shorten a provider wait."""

    current = _aware(now)
    candidates: list[datetime] = []
    floor = max(0.0, float(configured_floor_seconds))
    generated = max(0.0, float(generated_delay_seconds))
    if floor > 0:
        candidates.append(current + timedelta(seconds=floor))
    if generated > 0:
        candidates.append(current + timedelta(seconds=generated))
    for deadline in (server_deadline, persisted_deadline):
        if deadline is not None:
            candidates.append(_aware(deadline))
    if not candidates:
        return None
    latest = max(candidates)
    return latest if latest > current else None


@dataclass(frozen=True)
class BudgetAuthorization:
    budget_date: str
    authorized_at: datetime
    acknowledged_at: datetime | None = None

    @classmethod
    def authorize(cls, moment: datetime) -> "BudgetAuthorization":
        aware = _aware(moment)
        return cls(business_date_utc3(aware), aware)

    def acknowledge(self, moment: datetime) -> "BudgetAuthorization":
        return replace(self, acknowledged_at=_aware(moment))


@dataclass(frozen=True)
class EligibilityResult:
    allowed: bool
    reason: str
    next_allowed_at: datetime | None = None


def evaluate_eligibility(
    *,
    now: datetime,
    role: str,
    sampled_limit: int,
    quiet_limit: int,
    sent_count: int,
    route_ready: bool = True,
    tenant_sanction: str | None = None,
    server_deadline: datetime | None = None,
    persisted_deadline: datetime | None = None,
    unclear_wait: bool = False,
) -> EligibilityResult:
    """Evaluate local admission without performing or preparing a MAX call."""

    target = effective_daily_target(
        sampled_limit, role=role, quiet_limit=quiet_limit
    )
    if tenant_sanction == "confirmed_ban":
        return EligibilityResult(False, "tenant_stopped")
    if unclear_wait:
        return EligibilityResult(False, "review_required")
    if not route_ready:
        return EligibilityResult(False, "route_unavailable")
    if target <= 0:
        return EligibilityResult(False, "role_skip")
    if int(sent_count) >= target:
        return EligibilityResult(False, "daily_limit")
    deadline = next_allowed_at(
        now,
        server_deadline=server_deadline,
        persisted_deadline=persisted_deadline,
    )
    if deadline is not None:
        return EligibilityResult(False, "deadline", deadline)
    return EligibilityResult(True, "allowed")


@dataclass(frozen=True)
class FanoutReport:
    applied: list[int]
    failed: list[int]


def fan_out_pacing_settings(
    values: Mapping[str, object],
    tenant_ids: Sequence[int],
    apply: Callable[[int, dict[str, str]], None],
) -> FanoutReport:
    """Apply only allowlisted policy values and expose partial failures."""

    filtered = filter_pacing_updates(values)
    applied: list[int] = []
    failed: list[int] = []
    for tenant_id in tenant_ids:
        try:
            apply(int(tenant_id), dict(filtered))
        except Exception:
            failed.append(int(tenant_id))
        else:
            applied.append(int(tenant_id))
    return FanoutReport(applied=applied, failed=failed)
