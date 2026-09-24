"""T07: attempt identity, stage deadlines and idempotent input commands."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.auth_attempts import (
    AuthAttemptConflict,
    AuthAttemptExpired,
    AuthAttemptNotFound,
    AuthAttemptStore,
)


UTC = timezone.utc
START = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)


def _store() -> AuthAttemptStore:
    return AuthAttemptStore(clock=lambda: START)


def test_new_attempt_is_independent_of_previous_profile_error() -> None:
    store = _store()

    view, created = store.start(
        "tenant:1", 7, group_id=3, mode="fresh", request_id="start-1"
    )
    waiting = store.waiting_code(
        "tenant:1", 7, attempt_id=view.attempt_id, now=START + timedelta(seconds=5)
    )

    assert created is True
    assert waiting.auth_step == "waiting_sms"
    assert waiting.attempt_id == view.attempt_id
    assert waiting.error_code is None


def test_start_request_is_idempotent_and_different_start_is_rejected() -> None:
    store = _store()
    first, created = store.start(
        "local", 7, group_id=None, mode="fresh", request_id="same-request"
    )
    repeated, repeated_created = store.start(
        "local", 7, group_id=None, mode="fresh", request_id="same-request"
    )

    assert created is True
    assert repeated_created is False
    assert repeated.attempt_id == first.attempt_id
    with pytest.raises(AuthAttemptConflict, match="attempt_already_running"):
        store.start("local", 7, group_id=None, mode="fresh", request_id="other")


def test_stale_revision_and_wrong_stage_never_advance_attempt() -> None:
    store = _store()
    view, _ = store.start(
        "local", 7, group_id=None, mode="fresh", request_id="start"
    )

    with pytest.raises(AuthAttemptConflict, match="attempt_stage_conflict"):
        store.submit_code(
            "local",
            7,
            attempt_id=view.attempt_id,
            revision=view.revision,
            request_id="code-1",
        )

    waiting = store.waiting_code("local", 7, attempt_id=view.attempt_id)
    with pytest.raises(AuthAttemptConflict, match="revision_conflict"):
        store.submit_code(
            "local",
            7,
            attempt_id=waiting.attempt_id,
            revision=waiting.revision - 1,
            request_id="code-2",
        )
    assert store.get("local", 7, waiting.attempt_id).stage == "waiting_code"


def test_duplicate_code_command_has_one_transition_and_expired_input_is_rejected() -> None:
    store = _store()
    started, _ = store.start(
        "local", 7, group_id=None, mode="fresh", request_id="start"
    )
    waiting = store.waiting_code(
        "local", 7, attempt_id=started.attempt_id, now=START
    )
    verifying = store.submit_code(
        "local",
        7,
        attempt_id=waiting.attempt_id,
        revision=waiting.revision,
        request_id="code",
        now=START + timedelta(seconds=1),
    )
    repeated = store.submit_code(
        "local",
        7,
        attempt_id=waiting.attempt_id,
        revision=waiting.revision,
        request_id="code",
        now=START + timedelta(seconds=2),
    )

    assert verifying == repeated
    assert verifying.stage == "verifying_code"
    with pytest.raises(AuthAttemptConflict, match="attempt_stage_conflict"):
        store.submit_code(
            "local",
            7,
            attempt_id=waiting.attempt_id,
            revision=verifying.revision,
            request_id="second-code",
            now=START + timedelta(seconds=3),
        )


def test_password_retry_returns_to_waiting_password_without_new_challenge() -> None:
    store = _store()
    started, _ = store.start(
        "local", 7, group_id=None, mode="fresh", request_id="start"
    )
    waiting_code = store.waiting_code(
        "local", 7, attempt_id=started.attempt_id, now=START
    )
    verifying_code = store.submit_code(
        "local",
        7,
        attempt_id=waiting_code.attempt_id,
        revision=waiting_code.revision,
        request_id="code",
        now=START + timedelta(seconds=1),
    )
    waiting_password = store.waiting_password(
        "local", 7, attempt_id=verifying_code.attempt_id, hint="hint"
    )
    verifying_password = store.submit_password(
        "local",
        7,
        attempt_id=waiting_password.attempt_id,
        revision=waiting_password.revision,
        request_id="password-1",
        now=START + timedelta(seconds=2),
    )
    retried = store.waiting_password(
        "local",
        7,
        attempt_id=verifying_password.attempt_id,
        hint="hint",
        now=START + timedelta(seconds=3),
    )

    assert retried.stage == "waiting_password"
    assert retried.revision == verifying_password.revision + 1


def test_connection_deadline_expires_before_overall_attempt_deadline() -> None:
    store = _store()
    started, _ = store.start(
        "local", 7, group_id=None, mode="fresh", request_id="start"
    )

    expired = store.get(
        "local",
        7,
        started.attempt_id,
        now=START + timedelta(seconds=91),
    )

    assert expired.auth_step == "expired"
    assert expired.error_code == "CONNECTION_TIMEOUT"
    assert expired.attempt_deadline_at > START + timedelta(seconds=91)
    with pytest.raises(AuthAttemptExpired, match="CONNECTION_TIMEOUT"):
        store.submit_code(
            "local",
            7,
            attempt_id=started.attempt_id,
            revision=started.revision,
            request_id="late-code",
            now=START + timedelta(seconds=92),
        )


def test_scope_and_attempt_identity_are_required() -> None:
    store = _store()
    view, _ = store.start(
        "tenant:1", 7, group_id=None, mode="fresh", request_id="start"
    )

    with pytest.raises(AuthAttemptNotFound):
        store.get("tenant:2", 7, view.attempt_id)
    with pytest.raises(AuthAttemptNotFound):
        store.get("tenant:1", 7, "auth-missing")
