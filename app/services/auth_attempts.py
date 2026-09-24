"""Bounded, non-secret authentication-attempt state machine.

The MAX challenge and password remain in the runtime queue owned by the
adapter.  This module stores only attempt metadata and validates every input
against the current scope, attempt identity, revision and stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Callable
from uuid import uuid4


UTC = timezone.utc
CONNECT_TIMEOUT = timedelta(seconds=90)
INPUT_TIMEOUT = timedelta(seconds=300)
VERIFY_TIMEOUT = timedelta(seconds=90)
ATTEMPT_TIMEOUT = timedelta(seconds=600)


class AuthAttemptError(RuntimeError):
    """Safe, routable state-machine error."""

    status_code = 409

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AuthAttemptNotFound(AuthAttemptError):
    status_code = 404


class AuthAttemptConflict(AuthAttemptError):
    status_code = 409


class AuthAttemptExpired(AuthAttemptError):
    status_code = 410


@dataclass(frozen=True, slots=True)
class AuthAttemptView:
    scope: str
    profile_id: int
    group_id: int | None
    attempt_id: str
    revision: int
    mode: str
    stage: str
    stage_deadline_at: datetime | None
    attempt_deadline_at: datetime
    hint: str
    error_code: str | None

    @property
    def terminal(self) -> bool:
        return self.stage in {
            "succeeded",
            "error",
            "expired",
            "cancelled",
            "interrupted",
        }

    @property
    def auth_step(self) -> str:
        return {
            "connecting": "connecting",
            "waiting_code": "waiting_sms",
            "verifying_code": "verifying_sms",
            "waiting_password": "waiting_cloud_password",
            "verifying_password": "verifying_password",
            "succeeded": "idle",
            "error": "error",
            "expired": "expired",
            "cancelled": "idle",
            "interrupted": "error",
        }.get(self.stage, "error")

    def public(self) -> dict[str, object]:
        """Return only non-secret metadata for a profile/API projection."""
        return {
            "attempt_id": self.attempt_id,
            "revision": self.revision,
            "auth_step": self.auth_step,
            "auth_stage": self.stage,
            "auth_hint": self.hint,
            "auth_stage_deadline_at": _iso(self.stage_deadline_at),
            "auth_attempt_deadline_at": _iso(self.attempt_deadline_at),
            "auth_error_code": self.error_code,
        }

    def metadata(self) -> dict[str, object]:
        """Return the non-secret persistence projection for the repository."""
        return {
            "scope": self.scope,
            "profile_id": self.profile_id,
            "group_id": self.group_id,
            "attempt_id": self.attempt_id,
            "revision": self.revision,
            "mode": self.mode,
            "stage": self.stage,
            "auth_step": self.auth_step,
            "stage_deadline_at": _iso(self.stage_deadline_at),
            "attempt_deadline_at": _iso(self.attempt_deadline_at),
            "terminal": self.terminal,
            "error_code": self.error_code,
        }


@dataclass
class _Attempt:
    scope: str
    profile_id: int
    group_id: int | None
    attempt_id: str
    revision: int
    mode: str
    stage: str
    stage_deadline_at: datetime | None
    attempt_deadline_at: datetime
    hint: str
    error_code: str | None
    command_results: dict[tuple[str, str], AuthAttemptView]

    @property
    def terminal(self) -> bool:
        return self.stage in {
            "succeeded",
            "error",
            "expired",
            "cancelled",
            "interrupted",
        }

    def view(self) -> AuthAttemptView:
        return AuthAttemptView(
            scope=self.scope,
            profile_id=self.profile_id,
            group_id=self.group_id,
            attempt_id=self.attempt_id,
            revision=self.revision,
            mode=self.mode,
            stage=self.stage,
            stage_deadline_at=self.stage_deadline_at,
            attempt_deadline_at=self.attempt_deadline_at,
            hint=self.hint,
            error_code=self.error_code,
        )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("auth attempt clock must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value is not None else None


def _request_id(value: str | None) -> str:
    if value is None or not str(value).strip():
        return f"generated-{uuid4().hex}"
    candidate = str(value).strip()
    if len(candidate) > 128 or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
        for char in candidate
    ):
        raise AuthAttemptConflict("request_id_invalid")
    return candidate


class AuthAttemptStore:
    """Process-owned attempt metadata with explicit idempotency boundaries."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = RLock()
        self._attempts: dict[str, _Attempt] = {}
        self._active_by_profile: dict[tuple[str, int], str] = {}
        self._start_receipts: dict[tuple[str, int, str], str] = {}

    def _now(self, now: datetime | None) -> datetime:
        return _aware(now if now is not None else self._clock())

    @staticmethod
    def _profile_key(scope: str, profile_id: int) -> tuple[str, int]:
        normalized = str(scope).strip()
        if not normalized or int(profile_id) < 1:
            raise ValueError("scope_and_profile_required")
        return normalized, int(profile_id)

    def _expire_if_needed(self, attempt: _Attempt, now: datetime) -> None:
        if attempt.terminal:
            return
        code: str | None = None
        if now >= attempt.attempt_deadline_at:
            code = "ATTEMPT_EXPIRED"
        elif attempt.stage_deadline_at is not None and now >= attempt.stage_deadline_at:
            code = {
                "connecting": "CONNECTION_TIMEOUT",
                "waiting_code": "CODE_INPUT_TIMEOUT",
                "verifying_code": "CODE_INPUT_TIMEOUT",
                "waiting_password": "PASSWORD_INPUT_TIMEOUT",
                "verifying_password": "PASSWORD_INPUT_TIMEOUT",
            }.get(attempt.stage, "ATTEMPT_EXPIRED")
        if code is not None:
            attempt.stage = "expired"
            attempt.error_code = code
            attempt.stage_deadline_at = None
            attempt.revision += 1

    def _lookup(
        self,
        scope: str,
        profile_id: int,
        attempt_id: str,
        now: datetime,
    ) -> _Attempt:
        key = self._profile_key(scope, profile_id)
        attempt = self._attempts.get(str(attempt_id))
        if attempt is None or self._profile_key(attempt.scope, attempt.profile_id) != key:
            raise AuthAttemptNotFound("attempt_not_found")
        self._expire_if_needed(attempt, now)
        return attempt

    def start(
        self,
        scope: str,
        profile_id: int,
        *,
        group_id: int | None,
        mode: str,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> tuple[AuthAttemptView, bool]:
        """Create one attempt, or return the receipt for the same Start."""
        moment = self._now(now)
        key = self._profile_key(scope, profile_id)
        rid = _request_id(request_id)
        receipt_key = (*key, rid)
        with self._lock:
            prior_id = self._start_receipts.get(receipt_key)
            if prior_id is not None:
                prior = self._attempts.get(prior_id)
                if prior is not None:
                    self._expire_if_needed(prior, moment)
                    return prior.view(), False

            active_id = self._active_by_profile.get(key)
            if active_id is not None:
                active = self._attempts.get(active_id)
                if active is not None:
                    self._expire_if_needed(active, moment)
                    if not active.terminal:
                        raise AuthAttemptConflict("attempt_already_running")

            attempt = _Attempt(
                scope=key[0],
                profile_id=key[1],
                group_id=int(group_id) if group_id is not None else None,
                attempt_id=f"auth-{uuid4().hex}",
                revision=0,
                mode=str(mode or "explicit"),
                stage="connecting",
                stage_deadline_at=moment + CONNECT_TIMEOUT,
                attempt_deadline_at=moment + ATTEMPT_TIMEOUT,
                hint="",
                error_code=None,
                command_results={},
            )
            self._attempts[attempt.attempt_id] = attempt
            self._active_by_profile[key] = attempt.attempt_id
            self._start_receipts[receipt_key] = attempt.attempt_id
            return attempt.view(), True

    def get(
        self,
        scope: str,
        profile_id: int,
        attempt_id: str,
        *,
        now: datetime | None = None,
    ) -> AuthAttemptView:
        with self._lock:
            return self._lookup(scope, profile_id, attempt_id, self._now(now)).view()

    def current(
        self,
        scope: str,
        profile_id: int,
        *,
        now: datetime | None = None,
    ) -> AuthAttemptView | None:
        moment = self._now(now)
        key = self._profile_key(scope, profile_id)
        with self._lock:
            attempt_id = self._active_by_profile.get(key)
            if attempt_id is None:
                return None
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                return None
            self._expire_if_needed(attempt, moment)
            return attempt.view()

    def _require_revision(
        self,
        attempt: _Attempt,
        expected_revision: int,
        *,
        allowed_stages: set[str],
    ) -> None:
        if attempt.terminal:
            if attempt.stage == "expired":
                raise AuthAttemptExpired(attempt.error_code or "ATTEMPT_EXPIRED")
            if attempt.stage == "interrupted":
                raise AuthAttemptConflict("ATTEMPT_INTERRUPTED")
            raise AuthAttemptConflict("attempt_terminal")
        if int(expected_revision) != attempt.revision:
            raise AuthAttemptConflict("revision_conflict")
        if attempt.stage not in allowed_stages:
            raise AuthAttemptConflict("attempt_stage_conflict")

    def _transition(
        self,
        attempt: _Attempt,
        *,
        stage: str,
        stage_deadline: timedelta | None,
        now: datetime,
        hint: str = "",
        error_code: str | None = None,
    ) -> AuthAttemptView:
        attempt.stage = stage
        attempt.stage_deadline_at = (
            now + stage_deadline if stage_deadline is not None else None
        )
        attempt.hint = str(hint)[:200]
        attempt.error_code = error_code
        attempt.revision += 1
        if attempt.terminal:
            self._active_by_profile.pop(
                self._profile_key(attempt.scope, attempt.profile_id), None
            )
        return attempt.view()

    def waiting_code(
        self,
        scope: str,
        profile_id: int,
        *,
        attempt_id: str,
        now: datetime | None = None,
    ) -> AuthAttemptView:
        moment = self._now(now)
        with self._lock:
            attempt = self._lookup(scope, profile_id, attempt_id, moment)
            if attempt.stage not in {"connecting", "waiting_code"}:
                raise AuthAttemptConflict("attempt_stage_conflict")
            if attempt.stage == "waiting_code":
                return attempt.view()
            return self._transition(
                attempt, stage="waiting_code", stage_deadline=INPUT_TIMEOUT, now=moment
            )

    def waiting_password(
        self,
        scope: str,
        profile_id: int,
        *,
        attempt_id: str,
        hint: str | None = None,
        now: datetime | None = None,
    ) -> AuthAttemptView:
        moment = self._now(now)
        with self._lock:
            attempt = self._lookup(scope, profile_id, attempt_id, moment)
            if attempt.stage not in {
                "verifying_code",
                "verifying_password",
                "waiting_password",
            }:
                raise AuthAttemptConflict("attempt_stage_conflict")
            if attempt.stage == "waiting_password":
                return attempt.view()
            return self._transition(
                attempt,
                stage="waiting_password",
                stage_deadline=INPUT_TIMEOUT,
                now=moment,
                hint=hint or "",
            )

    def _submit(
        self,
        scope: str,
        profile_id: int,
        *,
        attempt_id: str,
        revision: int,
        request_id: str | None,
        command: str,
        expected_stage: str,
        verifying_stage: str,
        now: datetime | None,
    ) -> tuple[AuthAttemptView, bool]:
        moment = self._now(now)
        rid = _request_id(request_id)
        with self._lock:
            attempt = self._lookup(scope, profile_id, attempt_id, moment)
            receipt_key = (command, rid)
            prior = attempt.command_results.get(receipt_key)
            if prior is not None:
                return prior, False
            self._require_revision(
                attempt, revision, allowed_stages={expected_stage}
            )
            result = self._transition(
                attempt,
                stage=verifying_stage,
                stage_deadline=VERIFY_TIMEOUT,
                now=moment,
            )
            attempt.command_results[receipt_key] = result
            return result, True

    def _submit_public(
        self,
        *args: object,
        **kwargs: object,
    ) -> AuthAttemptView:
        result, _created = self._submit(*args, **kwargs)  # type: ignore[arg-type]
        return result

    def submit_code(
        self,
        scope: str,
        profile_id: int,
        *,
        attempt_id: str,
        revision: int,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> AuthAttemptView:
        return self._submit_public(
            scope,
            profile_id,
            attempt_id=attempt_id,
            revision=revision,
            request_id=request_id,
            command="code",
            expected_stage="waiting_code",
            verifying_stage="verifying_code",
            now=now,
        )

    def submit_code_once(
        self,
        scope: str,
        profile_id: int,
        *,
        attempt_id: str,
        revision: int,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> tuple[AuthAttemptView, bool]:
        return self._submit(
            scope,
            profile_id,
            attempt_id=attempt_id,
            revision=revision,
            request_id=request_id,
            command="code",
            expected_stage="waiting_code",
            verifying_stage="verifying_code",
            now=now,
        )

    def submit_password(
        self,
        scope: str,
        profile_id: int,
        *,
        attempt_id: str,
        revision: int,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> AuthAttemptView:
        return self._submit_public(
            scope,
            profile_id,
            attempt_id=attempt_id,
            revision=revision,
            request_id=request_id,
            command="password",
            expected_stage="waiting_password",
            verifying_stage="verifying_password",
            now=now,
        )

    def submit_password_once(
        self,
        scope: str,
        profile_id: int,
        *,
        attempt_id: str,
        revision: int,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> tuple[AuthAttemptView, bool]:
        return self._submit(
            scope,
            profile_id,
            attempt_id=attempt_id,
            revision=revision,
            request_id=request_id,
            command="password",
            expected_stage="waiting_password",
            verifying_stage="verifying_password",
            now=now,
        )

    def succeed(
        self,
        scope: str,
        profile_id: int,
        *,
        attempt_id: str,
        now: datetime | None = None,
    ) -> AuthAttemptView:
        moment = self._now(now)
        with self._lock:
            attempt = self._lookup(scope, profile_id, attempt_id, moment)
            if attempt.terminal:
                return attempt.view()
            return self._transition(
                attempt, stage="succeeded", stage_deadline=None, now=moment
            )

    def fail(
        self,
        scope: str,
        profile_id: int,
        *,
        attempt_id: str,
        error_code: str,
        now: datetime | None = None,
    ) -> AuthAttemptView:
        moment = self._now(now)
        with self._lock:
            attempt = self._lookup(scope, profile_id, attempt_id, moment)
            if attempt.terminal:
                return attempt.view()
            return self._transition(
                attempt,
                stage="error",
                stage_deadline=None,
                now=moment,
                error_code=str(error_code)[:64],
            )

    def cancel(
        self,
        scope: str,
        profile_id: int,
        *,
        attempt_id: str,
        now: datetime | None = None,
    ) -> AuthAttemptView:
        moment = self._now(now)
        with self._lock:
            attempt = self._lookup(scope, profile_id, attempt_id, moment)
            if attempt.terminal:
                return attempt.view()
            return self._transition(
                attempt,
                stage="cancelled",
                stage_deadline=None,
                now=moment,
                error_code="ATTEMPT_INTERRUPTED",
            )
