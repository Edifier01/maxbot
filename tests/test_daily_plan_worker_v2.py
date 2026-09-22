"""T33 worker-facing safeguards; no provider adapter is used."""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timezone

from app.repositories.daily_plans import DailyPlanRepository
from app.services.daily_plans import DailyPlanService, LibraryItem, WaitDecision


def test_unavailable_account_slot_is_not_transferred_to_another_account() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    service = DailyPlanService(DailyPlanRepository(connection))
    try:
        service.materialize_day(
            "tenant:1", 1, "2026-09-20", sampled_limit=1, role="active", quiet_limit=1,
            work_group_id=10,
            library_items=(LibraryItem("a", "account-a", "v1"),),
            rng=random.Random(1),
        )
        service.materialize_day(
            "tenant:1", 2, "2026-09-20", sampled_limit=1, role="active", quiet_limit=1,
            work_group_id=20,
            library_items=(LibraryItem("b", "account-b", "v1"),),
            rng=random.Random(1),
        )
        first = service.claim_next_slot(
            "tenant:1", datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
        )
        second = service.claim_next_slot(
            "tenant:1", datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
        )
        assert first.profile_id == 1
        assert second.profile_id == 2
        assert first.rendered_text == "account-a"
        assert second.rendered_text == "account-b"
    finally:
        connection.close()


def test_empty_library_keeps_sampled_target_and_waits_without_slots() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    service = DailyPlanService(DailyPlanRepository(connection))
    try:
        plan = service.materialize_day(
            "tenant:1", 1, "2026-09-20", sampled_limit=5, role="active", quiet_limit=1,
            work_group_id=10, library_items=(), rng=random.Random(1),
        )
        decision = service.claim_next_slot(
            "tenant:1", datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
        )
        assert plan.target == 5
        assert plan.slots == ()
        assert isinstance(decision, WaitDecision)
    finally:
        connection.close()
