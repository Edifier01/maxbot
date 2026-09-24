"""Personal account-day plans backed by immutable library snapshots."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.repositories.daily_plans import DailyPlanRepository
from app.services.pacing import business_date_utc3, effective_daily_target


class PoolEmptyError(RuntimeError):
    """A positive target cannot be materialized until a library is published."""


@dataclass(frozen=True)
class MessageSelection:
    item_id: str
    pass_index: int


@dataclass(frozen=True)
class LibraryItem:
    item_id: str
    text: str
    version_id: str


@dataclass(frozen=True)
class SlotView:
    slot_id: str
    profile_id: int
    work_group_id: int | None
    item_id: str
    pass_index: int
    version_id: str | None
    rendered_text: str
    status: str
    retry_count: int


@dataclass(frozen=True)
class DailyPlanView:
    scope: str
    plan_id: str
    profile_id: int
    business_date: str
    role: str
    sampled_limit: int
    target: int
    work_group_id: int | None
    version_id: str | None
    warning: str
    slots: tuple[SlotView, ...]


@dataclass(frozen=True)
class OperationView:
    slot_id: str
    plan_id: str
    profile_id: int
    work_group_id: int | None
    item_id: str
    rendered_text: str
    version_id: str | None
    retry_count: int


@dataclass(frozen=True)
class WaitDecision:
    reason: str


def select_daily_items(
    item_ids: tuple[str, ...],
    count: int,
    mode: Literal["random_norepeat", "round_robin"] | str,
    rng: random.Random,
) -> tuple[MessageSelection, ...]:
    if count < 0:
        raise ValueError("count must not be negative")
    if mode not in {"random_norepeat", "round_robin"}:
        raise ValueError(f"unsupported selection mode: {mode}")
    if len(set(item_ids)) != len(item_ids):
        raise ValueError("item_ids must be unique")
    if count == 0:
        return ()
    if not item_ids:
        raise PoolEmptyError("POOL_EMPTY")
    if mode == "round_robin":
        return tuple(
            MessageSelection(item_ids[index % len(item_ids)], index // len(item_ids))
            for index in range(count)
        )
    result: list[MessageSelection] = []
    previous: str | None = None
    pass_index = 0
    while len(result) < count:
        deck = list(item_ids)
        rng.shuffle(deck)
        if previous is not None and len(deck) > 1 and deck[0] == previous:
            deck[0], deck[1] = deck[1], deck[0]
        take = min(len(deck), count - len(result))
        result.extend(MessageSelection(item_id, pass_index) for item_id in deck[:take])
        previous = result[-1].item_id
        pass_index += 1
    return tuple(result)


class DailyPlanService:
    def __init__(self, repository: DailyPlanRepository) -> None:
        self.repository = repository

    def materialize_day(
        self,
        scope: str,
        profile_id: int,
        business_date: str,
        *,
        sampled_limit: int,
        role: str,
        quiet_limit: int,
        work_group_id: int | None,
        library_items: tuple[LibraryItem, ...],
        mode: str = "random_norepeat",
        rng: random.Random | object | None = None,
        accepted_count: int = 0,
    ) -> DailyPlanView:
        existing = self.repository.get_plan(scope, profile_id, business_date)
        if existing is not None:
            existing_plan, existing_slots = existing
            if (
                existing_plan["warning"] == "POOL_EMPTY"
                and not existing_slots
                and library_items
            ):
                if rng is None:
                    rng = random.Random()
                selections = select_daily_items(
                    tuple(item.item_id for item in library_items),
                    int(existing_plan["target"]),
                    mode,
                    rng,  # type: ignore[arg-type]
                )
                by_id = {item.item_id: item for item in library_items}
                slots = tuple(
                    {
                        "item_id": selection.item_id,
                        "pass_index": selection.pass_index,
                        "version_id": by_id[selection.item_id].version_id,
                        "rendered_text": by_id[selection.item_id].text,
                    }
                    for selection in selections
                )
                filled = self.repository.fill_waiting_plan(
                    scope=scope,
                    profile_id=profile_id,
                    business_date=business_date,
                    version_id=library_items[0].version_id,
                    slots=slots,
                )
                return self._view(scope, filled)
            return self._view(scope, existing)
        accepted = int(accepted_count)
        if accepted < 0:
            raise ValueError("accepted_count must not be negative")
        base_target = effective_daily_target(
            sampled_limit, role=role, quiet_limit=quiet_limit
        )
        if accepted > base_target:
            raise ValueError("accepted_count exceeds sampled target")
        target = base_target - accepted
        if rng is None:
            rng = random.Random()
        warning = ""
        version_id = library_items[0].version_id if library_items else None
        selections: tuple[MessageSelection, ...] = ()
        if target > 0:
            if not library_items:
                warning = "POOL_EMPTY"
            else:
                ids = tuple(item.item_id for item in library_items)
                selections = select_daily_items(ids, target, mode, rng)  # type: ignore[arg-type]
        by_id = {item.item_id: item for item in library_items}
        slots = tuple(
            {
                "item_id": selection.item_id,
                "pass_index": selection.pass_index,
                "version_id": by_id[selection.item_id].version_id,
                "rendered_text": by_id[selection.item_id].text,
            }
            for selection in selections
        )
        created = self.repository.create_plan(
            scope=scope,
            profile_id=profile_id,
            business_date=business_date,
            role=role,
            sampled_limit=max(0, int(sampled_limit)),
            quiet_limit=max(0, int(quiet_limit)),
            target=target,
            work_group_id=work_group_id,
            version_id=version_id,
            warning=warning,
            slots=slots,
        )
        return self._view(scope, created)

    def claim_next_slot(
        self,
        scope: str,
        now: datetime,
        *,
        eligible_assignments: tuple[tuple[int, int], ...] | None = None,
    ) -> OperationView | WaitDecision:
        row = self.repository.claim_next(
            scope,
            business_date_utc3(now),
            eligible_assignments=eligible_assignments,
        )
        if row is None:
            return WaitDecision("waiting_pool_or_no_queued_slot")
        return OperationView(
            slot_id=str(row["slot_id"]),
            plan_id=str(row["plan_id"]),
            profile_id=int(row["profile_id"]),
            work_group_id=(
                int(row["work_group_id"]) if row["work_group_id"] is not None else None
            ),
            item_id=str(row["item_id"]),
            rendered_text=str(row["rendered_text"]),
            version_id=(str(row["version_id"]) if row["version_id"] is not None else None),
            retry_count=int(row["retry_count"]),
        )

    def mark_slot_unknown(self, slot_id: str, reason: str) -> OperationView:
        row = self.repository.mark_unknown(slot_id, reason)
        return self._operation(row)

    def mark_slot_failed_unsent(self, slot_id: str, reason: str) -> OperationView:
        row = self.repository.mark_failed_unsent(slot_id, reason)
        return self._operation(row)

    def mark_slot_accepted(self, slot_id: str) -> OperationView:
        row = self.repository.mark_accepted(slot_id)
        return self._operation(row)

    def retry_slot(self, slot_id: str, *, proof_no_send: bool) -> OperationView:
        try:
            row = self.repository.retry(slot_id, proof_no_send=proof_no_send)
        except RuntimeError as exc:
            raise PoolEmptyError(str(exc)) from exc
        return self._operation(row)

    def cancel_queued_for_profile(
        self, scope: str, profile_id: int, reason: str
    ) -> int:
        return self.repository.cancel_queued_for_profile(scope, profile_id, reason)

    def expire_before(self, scope: str, business_date: str) -> int:
        return self.repository.expire_before(scope, business_date)

    def count_slots(self, scope: str, status: str | None = None) -> int:
        return self.repository.count_slots(scope, status)

    def _view(self, scope: str, data) -> DailyPlanView:
        plan, slots = data
        return DailyPlanView(
            scope=scope,
            plan_id=str(plan["plan_id"]),
            profile_id=int(plan["profile_id"]),
            business_date=str(plan["business_date"]),
            role=str(plan["role"]),
            sampled_limit=int(plan["sampled_limit"]),
            target=int(plan["target"]),
            work_group_id=(
                int(plan["work_group_id"]) if plan["work_group_id"] is not None else None
            ),
            version_id=(str(plan["version_id"]) if plan["version_id"] is not None else None),
            warning=str(plan["warning"] or ""),
            slots=tuple(
                SlotView(
                    slot_id=str(slot["slot_id"]),
                    profile_id=int(plan["profile_id"]),
                    work_group_id=(
                        int(plan["work_group_id"])
                        if plan["work_group_id"] is not None
                        else None
                    ),
                    item_id=str(slot["item_id"]),
                    pass_index=int(slot["pass_index"]),
                    version_id=(
                        str(slot["version_id"]) if slot["version_id"] is not None else None
                    ),
                    rendered_text=str(slot["rendered_text"]),
                    status=str(slot["status"]),
                    retry_count=int(slot["retry_count"]),
                )
                for slot in slots
            ),
        )

    @staticmethod
    def _operation(row) -> OperationView:
        return OperationView(
            slot_id=str(row["slot_id"]),
            plan_id=str(row["plan_id"]),
            profile_id=int(row["profile_id"]),
            work_group_id=(
                int(row["work_group_id"]) if row["work_group_id"] is not None else None
            ),
            item_id=str(row["item_id"]),
            rendered_text=str(row["rendered_text"]),
            version_id=(str(row["version_id"]) if row["version_id"] is not None else None),
            retry_count=int(row["retry_count"]),
        )
