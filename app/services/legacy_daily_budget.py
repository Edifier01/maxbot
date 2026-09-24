"""Read-only guard for legacy account-day budget migration."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date


@dataclass(frozen=True)
class LegacyBudgetFinding:
    profile_id: int
    status: str
    sampled_limit: int | None
    accepted_today: int | None
    remaining: int | None
    reason: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _integer(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def inspect_legacy_daily_budgets(
    connection: sqlite3.Connection,
    business_date: str,
) -> tuple[LegacyBudgetFinding, ...]:
    """Classify legacy counters without writing, sampling, or calling a provider.

    A current-day counter is trusted only when its accepted legacy send-log
    count agrees.  Any contradiction is a review gate rather than permission
    to allocate a fresh budget.
    """
    day = date.fromisoformat(str(business_date))
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='profiles'"
    ).fetchone() is None:
        # The worker bootstrap fixture (and a fresh, pre-schema database) has
        # no accounts whose legacy budget could require migration review.
        return ()
    profiles = connection.execute(
        "SELECT id, daily_limit, daily_limit_day, sent_day, "
        "messages_sent_today FROM profiles WHERE status='active' "
        "ORDER BY id"
    ).fetchall()
    send_log_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(send_log)").fetchall()
    }

    can_count_legacy_sends = {
        "profile_id",
        "status",
        "sent_at",
    }.issubset(send_log_columns)
    findings: list[LegacyBudgetFinding] = []
    for profile in profiles:
        profile_id = int(profile["id"])
        counter = _integer(profile["messages_sent_today"])
        sent_day_raw = str(profile["sent_day"] or "").strip()
        if counter is None or counter < 0:
            findings.append(
                LegacyBudgetFinding(
                    profile_id,
                    "MIGRATION_REVIEW_REQUIRED",
                    None,
                    None,
                    None,
                    "invalid_legacy_counter",
                )
            )
            continue
        if not sent_day_raw:
            if counter == 0:
                findings.append(
                    LegacyBudgetFinding(
                        profile_id,
                        "NO_CURRENT_DAY",
                        None,
                        0,
                        None,
                        "sent_day_not_set_and_counter_zero",
                    )
                )
            else:
                findings.append(
                    LegacyBudgetFinding(
                        profile_id,
                        "MIGRATION_REVIEW_REQUIRED",
                        None,
                        None,
                        None,
                        "counter_without_sent_day",
                    )
                )
            continue
        try:
            sent_day = date.fromisoformat(sent_day_raw[:10])
        except ValueError:
            findings.append(
                LegacyBudgetFinding(
                    profile_id,
                    "MIGRATION_REVIEW_REQUIRED",
                    None,
                    None,
                    None,
                    "invalid_sent_day",
                )
            )
            continue
        if sent_day < day:
            findings.append(
                LegacyBudgetFinding(
                    profile_id,
                    "NO_CURRENT_DAY",
                    None,
                    0,
                    None,
                    "counter_belongs_to_previous_day",
                )
            )
            continue
        if sent_day > day:
            findings.append(
                LegacyBudgetFinding(
                    profile_id,
                    "MIGRATION_REVIEW_REQUIRED",
                    None,
                    None,
                    None,
                    "counter_is_from_future_day",
                )
            )
            continue

        sampled_limit = _integer(profile["daily_limit"])
        limit_day = str(profile["daily_limit_day"] or "").strip()
        if sampled_limit is None or sampled_limit < 0 or limit_day[:10] != business_date:
            findings.append(
                LegacyBudgetFinding(
                    profile_id,
                    "MIGRATION_REVIEW_REQUIRED",
                    sampled_limit,
                    None,
                    None,
                    "current_day_limit_missing_or_unpinned",
                )
            )
            continue
        if not can_count_legacy_sends:
            findings.append(
                LegacyBudgetFinding(
                    profile_id,
                    "MIGRATION_REVIEW_REQUIRED",
                    sampled_limit,
                    None,
                    None,
                    "legacy_send_history_unavailable",
                )
            )
            continue
        logged = connection.execute(
            "SELECT COUNT(*) FROM send_log WHERE profile_id=? AND status='sent' "
            "AND date(sent_at, '+3 hours')=?",
            (profile_id, business_date),
        ).fetchone()
        logged_count = int(logged[0] if logged else 0)
        if logged_count != counter or counter > sampled_limit:
            findings.append(
                LegacyBudgetFinding(
                    profile_id,
                    "MIGRATION_REVIEW_REQUIRED",
                    sampled_limit,
                    None,
                    None,
                    "counter_and_accepted_history_disagree",
                )
            )
            continue
        findings.append(
            LegacyBudgetFinding(
                profile_id,
                "READY",
                sampled_limit,
                counter,
                sampled_limit - counter,
                "accepted_history_verified",
            )
        )
    return tuple(findings)
