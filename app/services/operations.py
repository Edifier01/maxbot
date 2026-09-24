"""Conservative operation-ledger policy for campaign sends."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import sqlite3

from app.repositories.operations import OperationRecord, OperationRepository


class OperationValidationError(ValueError):
    """The requested transition violates an immutable operation invariant."""


class OperationNotRetryable(RuntimeError):
    """The operation has an ambiguous or exhausted external outcome."""


@dataclass(frozen=True)
class OperationFinalization:
    record: OperationRecord
    housekeeping_errors: tuple[str, ...]


class OperationLedger:
    """Public state machine used by workers and command handlers.

    No method here performs a provider call.  Crossing that boundary is the
    caller's responsibility after ``mark_in_flight`` has committed.
    """

    def __init__(self, repository: OperationRepository) -> None:
        self.repository = repository

    def create_operation(
        self,
        *,
        scope: str,
        profile_id: int,
        group_id: int | None,
        text: str,
        request_id: str | None = None,
        command: str | None = None,
        operation_id: str | None = None,
        budget_date: str | None = None,
        daily_plan_id: str | None = None,
        slot_id: str | None = None,
        route_snapshot: dict[str, object] | None = None,
        max_pre_effect_retries: int = 2,
        reservation_guard: Callable[[sqlite3.Connection], None] | None = None,
    ) -> OperationRecord:
        return self.repository.create(
            scope=scope,
            profile_id=profile_id,
            group_id=group_id,
            text=text,
            operation_id=operation_id,
            request_id=request_id,
            command=command,
            budget_date=budget_date,
            daily_plan_id=daily_plan_id,
            slot_id=slot_id,
            route_snapshot=route_snapshot,
            max_pre_effect_retries=max_pre_effect_retries,
            reservation_guard=reservation_guard,
        )

    def get(self, operation_id: str) -> OperationRecord:
        record = self.repository.get(operation_id)
        if record is None:
            raise OperationValidationError("operation not found")
        return record

    def claim(self, operation_id: str, *, profile_id: int) -> OperationRecord:
        try:
            return self.repository.claim(operation_id, profile_id=profile_id)
        except ValueError as exc:
            raise OperationValidationError(str(exc)) from exc

    def mark_in_flight(
        self,
        operation_id: str,
        *,
        route_snapshot: dict[str, object] | None = None,
    ) -> OperationRecord:
        try:
            return self.repository.mark_in_flight(
                operation_id, route_snapshot=route_snapshot
            )
        except (KeyError, RuntimeError) as exc:
            raise OperationValidationError(str(exc)) from exc

    def mark_failed_unsent(self, operation_id: str, error: str) -> OperationRecord:
        try:
            return self.repository.mark_failed_unsent(operation_id, error)
        except RuntimeError as exc:
            raise OperationValidationError(str(exc)) from exc

    def retry(
        self,
        operation_id: str,
        *,
        proof_no_send: bool,
        profile_id: int | None = None,
    ) -> OperationRecord:
        if profile_id is not None:
            current = self.get(operation_id)
            if current.profile_id != int(profile_id):
                raise OperationValidationError("operation belongs to a different profile")
        try:
            return self.repository.retry(operation_id, proof_no_send=proof_no_send)
        except RuntimeError as exc:
            raise OperationNotRetryable(str(exc)) from exc

    def mark_unknown(self, operation_id: str, error: str) -> OperationRecord:
        try:
            return self.repository.mark_unknown(operation_id, error)
        except RuntimeError as exc:
            raise OperationValidationError(str(exc)) from exc

    def mark_accepted(
        self, operation_id: str, *, provider_message_id: str
    ) -> OperationRecord:
        try:
            return self.repository.mark_accepted(
                operation_id, provider_message_id=provider_message_id
            )
        except ValueError as exc:
            raise OperationValidationError(str(exc)) from exc
        except RuntimeError as exc:
            raise OperationValidationError(str(exc)) from exc

    def finalize_accepted(
        self,
        operation_id: str,
        *,
        provider_message_id: str,
        post_commit_hooks: Iterable[Callable[[], object]] = (),
    ) -> list[str]:
        """Commit remote acknowledgement once, then isolate housekeeping errors."""

        self.mark_accepted(operation_id, provider_message_id=provider_message_id)
        errors: list[str] = []
        for hook in post_commit_hooks:
            try:
                hook()
            except Exception as exc:  # housekeeping cannot downgrade accepted
                errors.append(str(exc)[:500])
        return errors

    def recover(self) -> list[str]:
        return self.repository.recover_in_flight()
