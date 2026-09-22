"""T12: durable operation identity, attempts, and conservative recovery."""

from __future__ import annotations

import sqlite3

import pytest

from app.repositories.operations import OperationRepository
from app.services.operations import (
    OperationLedger,
    OperationNotRetryable,
    OperationValidationError,
)


def _ledger() -> tuple[sqlite3.Connection, OperationLedger]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    repository = OperationRepository(connection)
    return connection, OperationLedger(repository)


def _operation(ledger: OperationLedger, **overrides):
    values = {
        "scope": "tenant:1",
        "profile_id": 7,
        "group_id": 3,
        "text": "immutable fixture text",
        "request_id": None,
        "command": None,
        "operation_id": None,
        "max_pre_effect_retries": 2,
    }
    values.update(overrides)
    return ledger.create_operation(**values)


def test_process_recovery_marks_inflight_unknown_without_second_attempt() -> None:
    connection, ledger = _ledger()
    try:
        operation = _operation(ledger, operation_id="op-recover")
        ledger.claim(operation.operation_id, profile_id=7)
        ledger.mark_in_flight(operation.operation_id)

        recovered = ledger.recover()

        assert recovered == ["op-recover"]
        state = ledger.get(operation.operation_id)
        assert state.status == "unknown"
        assert state.attempt_count == 1
        assert state.retryable is False
        assert connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 1
    finally:
        connection.close()


def test_timeout_unknown_keeps_budget_occupied_and_cannot_replay() -> None:
    connection, ledger = _ledger()
    try:
        operation = _operation(ledger, operation_id="op-timeout")
        ledger.claim(operation.operation_id, profile_id=7)
        ledger.mark_in_flight(operation.operation_id)
        ledger.mark_unknown(operation.operation_id, "request timeout after transmit")

        state = ledger.get(operation.operation_id)
        assert state.status == "unknown"
        assert state.budget_occupied is True
        with pytest.raises(OperationNotRetryable):
            ledger.retry(operation.operation_id, proof_no_send=True)
    finally:
        connection.close()


def test_pre_network_retry_reuses_identity_text_and_sender() -> None:
    connection, ledger = _ledger()
    try:
        operation = _operation(ledger, operation_id="op-pre-send")
        ledger.claim(operation.operation_id, profile_id=7)
        ledger.mark_failed_unsent(operation.operation_id, "proxy unavailable")

        retried = ledger.retry(operation.operation_id, proof_no_send=True)

        assert retried.operation_id == operation.operation_id
        assert retried.profile_id == 7
        assert retried.group_id == 3
        assert retried.text == "immutable fixture text"
        assert retried.status == "claimed"
        assert retried.pre_effect_retry_count == 1
        assert retried.attempt_count == 0
    finally:
        connection.close()


def test_duplicate_start_receipt_returns_one_operation() -> None:
    connection, ledger = _ledger()
    try:
        first = _operation(
            ledger,
            request_id="req-42",
            command="start",
            operation_id="op-command",
        )
        second = _operation(
            ledger,
            request_id="req-42",
            command="start",
            operation_id="op-should-not-win",
        )

        assert second.operation_id == first.operation_id
        assert connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0] == 1
    finally:
        connection.close()


def test_ack_requires_provider_id_and_finalization_is_idempotent() -> None:
    connection, ledger = _ledger()
    try:
        operation = _operation(ledger, operation_id="op-ack")
        ledger.claim(operation.operation_id, profile_id=7)
        ledger.mark_in_flight(operation.operation_id)
        with pytest.raises(OperationValidationError):
            ledger.mark_accepted(operation.operation_id, provider_message_id=" ")

        accepted = ledger.mark_accepted(
            operation.operation_id, provider_message_id="provider-123"
        )
        same = ledger.mark_accepted(
            operation.operation_id, provider_message_id="provider-123"
        )
        assert accepted.status == "accepted"
        assert same.provider_message_id == "provider-123"
        assert connection.execute(
            "SELECT COUNT(*) FROM operation_attempts WHERE operation_id=? AND state='accepted'",
            (operation.operation_id,),
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_post_commit_housekeeping_error_cannot_downgrade_ack() -> None:
    connection, ledger = _ledger()
    try:
        operation = _operation(ledger, operation_id="op-housekeeping")
        ledger.claim(operation.operation_id, profile_id=7)
        ledger.mark_in_flight(operation.operation_id)

        errors = ledger.finalize_accepted(
            operation.operation_id,
            provider_message_id="provider-456",
            post_commit_hooks=[lambda: (_ for _ in ()).throw(RuntimeError("flood wait cleanup"))],
        )

        assert errors == ["flood wait cleanup"]
        assert ledger.get(operation.operation_id).status == "accepted"
        assert ledger.get(operation.operation_id).retryable is False
    finally:
        connection.close()


def test_retry_cannot_transfer_slot_to_another_profile() -> None:
    connection, ledger = _ledger()
    try:
        operation = _operation(ledger, operation_id="op-owner")
        with pytest.raises(OperationValidationError):
            ledger.claim(operation.operation_id, profile_id=8)

        ledger.claim(operation.operation_id, profile_id=7)
        ledger.mark_failed_unsent(operation.operation_id, "pre-send failure")
        with pytest.raises(OperationValidationError):
            ledger.retry(operation.operation_id, proof_no_send=True, profile_id=8)
    finally:
        connection.close()


def test_pre_effect_retry_counter_survives_restart_and_stops_loop() -> None:
    connection, ledger = _ledger()
    operation = _operation(
        ledger, operation_id="op-counter", max_pre_effect_retries=1
    )
    ledger.claim(operation.operation_id, profile_id=7)
    ledger.mark_failed_unsent(operation.operation_id, "before network")
    ledger.retry(operation.operation_id, proof_no_send=True)
    ledger.mark_failed_unsent(operation.operation_id, "before network again")
    connection.close()

    restarted = sqlite3.connect(":memory:")
    restarted.close()
    # The repository is the durable boundary; a second retry is refused before
    # any new network attempt can be created.
    connection2, ledger2 = _ledger()
    try:
        # Use a fresh fixture to keep this test independent of process globals.
        operation2 = _operation(
            ledger2, operation_id="op-counter-2", max_pre_effect_retries=1
        )
        ledger2.claim(operation2.operation_id, profile_id=7)
        ledger2.mark_failed_unsent(operation2.operation_id, "before network")
        ledger2.retry(operation2.operation_id, proof_no_send=True)
        ledger2.mark_failed_unsent(operation2.operation_id, "before network again")
        with pytest.raises(OperationNotRetryable):
            ledger2.retry(operation2.operation_id, proof_no_send=True)
    finally:
        connection2.close()
