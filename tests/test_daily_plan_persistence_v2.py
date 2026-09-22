"""T33 persistence and restart boundaries."""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timezone

from app.repositories.daily_plans import DailyPlanRepository
from app.services.daily_plans import DailyPlanService, LibraryItem


def _items() -> tuple[LibraryItem, ...]:
    return tuple(LibraryItem(f"item-{i}", f"text-{i}", "version-v1") for i in range(5))


def test_restart_preserves_same_plan_and_pinned_route(tmp_path) -> None:
    db_path = tmp_path / "tenant.db"
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    service = DailyPlanService(DailyPlanRepository(connection))
    first = service.materialize_day(
        "tenant:1", 7, "2026-09-20", sampled_limit=5, role="active", quiet_limit=1,
        work_group_id=3, library_items=_items(), rng=random.Random(4),
    )
    connection.close()

    restarted_connection = sqlite3.connect(db_path)
    restarted_connection.row_factory = sqlite3.Row
    restarted = DailyPlanService(DailyPlanRepository(restarted_connection))
    second = restarted.materialize_day(
        "tenant:1", 7, "2026-09-20", sampled_limit=99, role="skip", quiet_limit=0,
        work_group_id=8, library_items=(), rng=random.Random(99),
    )
    assert second.plan_id == first.plan_id
    assert second.target == 5
    assert second.work_group_id == 3
    assert [slot.rendered_text for slot in second.slots] == [
        slot.rendered_text for slot in first.slots
    ]
    restarted_connection.close()


def test_three_accepted_one_unknown_one_queued_does_not_create_sixth_slot() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    service = DailyPlanService(DailyPlanRepository(connection))
    try:
        service.materialize_day(
            "tenant:1", 7, "2026-09-20", sampled_limit=5, role="active", quiet_limit=1,
            work_group_id=3, library_items=_items(), rng=random.Random(4),
        )
        claimed = []
        for _ in range(4):
            claimed.append(
                service.claim_next_slot(
                    "tenant:1", datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
                )
            )
        for item in claimed[:3]:
            service.mark_slot_accepted(item.slot_id)
        service.mark_slot_unknown(claimed[3].slot_id, "timeout after request")
        last = service.claim_next_slot(
            "tenant:1", datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
        )
        service.mark_slot_accepted(last.slot_id)
        assert service.count_slots("tenant:1") == 5
        assert service.count_slots("tenant:1", status="accepted") == 4
        assert service.count_slots("tenant:1", status="unknown") == 1
        assert service.claim_next_slot(
            "tenant:1", datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
        ).reason == "waiting_pool_or_no_queued_slot"
    finally:
        connection.close()


def test_waiting_pool_fills_once_after_first_publication_without_resampling() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    service = DailyPlanService(DailyPlanRepository(connection))
    try:
        waiting = service.materialize_day(
            "tenant:1", 7, "2026-09-20", sampled_limit=5, role="active", quiet_limit=1,
            work_group_id=3, library_items=(), rng=random.Random(4),
        )
        filled = service.materialize_day(
            "tenant:1", 7, "2026-09-20", sampled_limit=99, role="skip", quiet_limit=0,
            work_group_id=8, library_items=_items(), rng=random.Random(4),
        )
        again = service.materialize_day(
            "tenant:1", 7, "2026-09-20", sampled_limit=1, role="quiet", quiet_limit=1,
            work_group_id=9, library_items=_items(), rng=random.Random(99),
        )
        assert waiting.warning == "POOL_EMPTY"
        assert filled.plan_id == waiting.plan_id
        assert filled.target == 5
        assert len(filled.slots) == 5
        assert again.slots == filled.slots
    finally:
        connection.close()
