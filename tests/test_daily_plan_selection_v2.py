"""T33: independent account-day selection and durable slot ownership."""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timezone

import pytest

from app.repositories.daily_plans import DailyPlanRepository
from app.services.daily_plans import (
    DailyPlanService,
    LibraryItem,
    MessageSelection,
    PoolEmptyError,
    WaitDecision,
    select_daily_items,
)


def _service() -> tuple[sqlite3.Connection, DailyPlanService]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    return connection, DailyPlanService(DailyPlanRepository(connection))


def _items(n: int = 5) -> tuple[LibraryItem, ...]:
    return tuple(LibraryItem(f"item-{i}", f"text-{i}", "version-v1") for i in range(n))


def test_selection_uses_distinct_items_before_starting_personal_pass() -> None:
    selections = select_daily_items(
        tuple(item.item_id for item in _items(3)),
        5,
        "random_norepeat",
        random.Random(3),
    )
    assert len(selections) == 5
    assert all(isinstance(item, MessageSelection) for item in selections)
    assert len({item.item_id for item in selections[:3]}) == 3
    assert [item.pass_index for item in selections] == [0, 0, 0, 1, 1]
    assert selections[2].item_id != selections[3].item_id


def test_library_items_are_reused_for_each_account_pass_without_mutation() -> None:
    from app.repositories.message_sets import MessageSetRepository

    connection, service = _service()
    try:
        repository = MessageSetRepository(connection)
        version_id, checksum = repository.publish("tenant:1", ("text-a", "text-b"))
        items = tuple(
            LibraryItem(str(row["item_id"]), str(row["text"]), version_id)
            for row in repository.items("tenant:1", version_id)
        )
        first = service.materialize_day(
            "tenant:1", 7, "2026-09-20", sampled_limit=5, role="active", quiet_limit=1,
            work_group_id=3, library_items=items, rng=random.Random(7),
        )
        second = service.materialize_day(
            "tenant:1", 8, "2026-09-20", sampled_limit=5, role="active", quiet_limit=1,
            work_group_id=4, library_items=items, rng=random.Random(8),
        )

        assert checksum
        assert first.target == second.target == 5
        assert [slot.pass_index for slot in first.slots] == [0, 0, 1, 1, 2]
        assert [slot.pass_index for slot in second.slots] == [0, 0, 1, 1, 2]
        assert {slot.version_id for slot in first.slots + second.slots} == {version_id}
        assert [row["text"] for row in repository.items("tenant:1", version_id)] == [
            "text-a",
            "text-b",
        ]
        assert repository.current("tenant:1")["version_id"] == version_id
    finally:
        connection.close()


def test_empty_pool_waits_without_creating_slots() -> None:
    with pytest.raises(PoolEmptyError):
        select_daily_items((), 5, "random_norepeat", random.Random(1))


def test_materialize_is_idempotent_and_preserves_pinned_texts_and_target() -> None:
    connection, service = _service()
    try:
        first = service.materialize_day(
            "tenant:1",
            7,
            "2026-09-20",
            sampled_limit=5,
            role="active",
            quiet_limit=1,
            work_group_id=3,
            library_items=_items(5),
            mode="random_norepeat",
            rng=random.Random(5),
        )

        class NoRandom:
            def shuffle(self, _items):
                raise AssertionError("existing plan must not resample")

        second = service.materialize_day(
            "tenant:1",
            7,
            "2026-09-20",
            sampled_limit=99,
            role="skip",
            quiet_limit=0,
            work_group_id=999,
            library_items=_items(1),
            mode="random_norepeat",
            rng=NoRandom(),
        )
        assert second == first
        assert first.target == 5
        assert len(first.slots) == 5
        assert {slot.version_id for slot in first.slots} == {"version-v1"}
        assert connection.execute("SELECT COUNT(*) FROM profile_daily_plans").fetchone()[0] == 1
    finally:
        connection.close()


def test_accounts_have_independent_plans_and_skip_has_no_slots() -> None:
    connection, service = _service()
    try:
        active = service.materialize_day(
            "tenant:1", 1, "2026-09-20", sampled_limit=5, role="active", quiet_limit=1,
            work_group_id=3, library_items=_items(5), rng=random.Random(1),
        )
        quiet = service.materialize_day(
            "tenant:1", 2, "2026-09-20", sampled_limit=5, role="quiet", quiet_limit=1,
            work_group_id=3, library_items=_items(5), rng=random.Random(2),
        )
        skipped = service.materialize_day(
            "tenant:1", 3, "2026-09-20", sampled_limit=5, role="skip", quiet_limit=1,
            work_group_id=3, library_items=_items(5), rng=random.Random(3),
        )
        assert active.target == 5 and len(active.slots) == 5
        assert quiet.target == 1 and len(quiet.slots) == 1
        assert skipped.target == 0 and skipped.slots == ()
    finally:
        connection.close()


def test_claim_executes_existing_queued_slot_without_quota_recheck() -> None:
    connection, service = _service()
    try:
        plan = service.materialize_day(
            "tenant:1", 7, "2026-09-20", sampled_limit=5, role="active", quiet_limit=1,
            work_group_id=3, library_items=_items(5), rng=random.Random(4),
        )
        claimed = service.claim_next_slot(
            "tenant:1", datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
        )
        assert claimed.plan_id == plan.plan_id
        assert claimed.profile_id == 7
        assert service.count_slots("tenant:1") == 5
    finally:
        connection.close()


def test_unknown_slot_is_occupied_and_old_queued_slots_expire_without_replacement() -> None:
    connection, service = _service()
    try:
        service.materialize_day(
            "tenant:1", 7, "2026-09-19", sampled_limit=5, role="active", quiet_limit=1,
            work_group_id=3, library_items=_items(5), rng=random.Random(4),
        )
        claimed = service.claim_next_slot(
            "tenant:1", datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
        )
        service.mark_slot_unknown(claimed.slot_id, "timeout")
        expired = service.expire_before("tenant:1", "2026-09-20")
        assert expired == 4
        assert service.count_slots("tenant:1", status="unknown") == 1
        assert service.count_slots("tenant:1", status="expired") == 4
        assert service.count_slots("tenant:1") == 5
        decision = service.claim_next_slot(
            "tenant:1", datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
        )
        assert isinstance(decision, WaitDecision)
    finally:
        connection.close()


def test_pre_send_slot_retry_keeps_same_slot_and_account() -> None:
    connection, service = _service()
    try:
        service.materialize_day(
            "tenant:1", 7, "2026-09-20", sampled_limit=1, role="active", quiet_limit=1,
            work_group_id=3, library_items=_items(5), rng=random.Random(4),
        )
        claimed = service.claim_next_slot(
            "tenant:1", datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
        )
        retried = service.retry_slot(claimed.slot_id, proof_no_send=True)
        assert retried.slot_id == claimed.slot_id
        assert retried.profile_id == claimed.profile_id == 7
        assert service.count_slots("tenant:1") == 1
    finally:
        connection.close()


def test_round_robin_is_the_explicit_non_random_selection_mode() -> None:
    selections = select_daily_items(
        ("m1", "m2"), 5, "round_robin", random.Random(1)
    )
    assert [item.item_id for item in selections] == ["m1", "m2", "m1", "m2", "m1"]


@pytest.mark.parametrize(
    ("items", "count", "mode"),
    [(("m1",), -1, "random_norepeat"), (("m1", "m1"), 2, "random_norepeat")],
)
def test_selection_rejects_invalid_inputs(
    items: tuple[str, ...], count: int, mode: str
) -> None:
    with pytest.raises(ValueError):
        select_daily_items(items, count, mode, random.Random(1))
