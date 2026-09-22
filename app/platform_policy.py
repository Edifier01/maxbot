"""Fail-closed authorization scope for MAX platform actions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal


class MaxAction(StrEnum):
    CONNECT = "connect"
    REQUEST_OTP = "request_otp"
    VERIFY_AUTH = "verify_auth"
    RESOLVE_DESTINATION = "resolve_destination"
    CHECK_DESTINATION = "check_destination"
    JOIN_DESTINATION = "join_destination"
    SEND = "send"
    FETCH_HISTORY = "fetch_history"
    MARK_READ = "mark_read"
    ADD_REACTION = "add_reaction"
    PROBE = "probe"


class MaxTransport(StrEnum):
    AUTHORIZED_USER_SESSION = "authorized_user_session"
    FAKE = "fake"


@dataclass(frozen=True, slots=True)
class AuthorizationRecord:
    schema_version: Literal[1]
    reference: str
    transport: MaxTransport
    allowed_actions: frozenset[MaxAction]
    valid_from: datetime
    valid_until: datetime


class PlatformAuthorizationHold(RuntimeError):
    """Raised whenever a platform action cannot be authorized fail-closed."""


_RECORD_FIELDS = {
    "schema_version",
    "reference",
    "transport",
    "allowed_actions",
    "valid_from",
    "valid_until",
}
_MAX_RECORD_BYTES = 16 * 1024


def _aware_datetime(raw: object) -> datetime:
    if not isinstance(raw, str):
        raise PlatformAuthorizationHold("timestamp_invalid")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlatformAuthorizationHold("timestamp_invalid") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise PlatformAuthorizationHold("timestamp_not_aware")
    return value


def _require_aware_now(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise PlatformAuthorizationHold("clock_not_aware")


def require_action_window(record: AuthorizationRecord, *, now: datetime) -> None:
    _require_aware_now(now)
    if now < record.valid_from or now >= record.valid_until:
        raise PlatformAuthorizationHold("record_expired")


def load_authorization_record(path: Path, *, now: datetime) -> AuthorizationRecord:
    """Load and validate one bounded, non-secret authorization record."""
    if not path.is_file():
        raise PlatformAuthorizationHold("record_missing")
    raw = path.read_bytes()
    if len(raw) > _MAX_RECORD_BYTES:
        raise PlatformAuthorizationHold("record_too_large")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlatformAuthorizationHold("record_malformed") from exc
    if not isinstance(payload, dict) or set(payload) != _RECORD_FIELDS:
        raise PlatformAuthorizationHold("record_fields_invalid")
    if payload["schema_version"] != 1:
        raise PlatformAuthorizationHold("record_version_invalid")

    reference = payload["reference"]
    if (
        not isinstance(reference, str)
        or not 1 <= len(reference) <= 200
        or not reference.isprintable()
    ):
        raise PlatformAuthorizationHold("record_reference_invalid")
    if payload["transport"] != MaxTransport.AUTHORIZED_USER_SESSION.value:
        raise PlatformAuthorizationHold("transport_not_supported")

    raw_actions = payload["allowed_actions"]
    if not isinstance(raw_actions, list):
        raise PlatformAuthorizationHold("record_actions_invalid")
    try:
        actions = frozenset(MaxAction(value) for value in raw_actions)
    except (TypeError, ValueError) as exc:
        raise PlatformAuthorizationHold("record_actions_invalid") from exc

    valid_from = _aware_datetime(payload["valid_from"])
    valid_until = _aware_datetime(payload["valid_until"])
    if valid_from >= valid_until:
        raise PlatformAuthorizationHold("record_window_invalid")
    record = AuthorizationRecord(
        schema_version=1,
        reference=reference,
        transport=MaxTransport.AUTHORIZED_USER_SESSION,
        allowed_actions=actions,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    require_action_window(record, now=now)
    return record


def require_action(
    record: AuthorizationRecord,
    action: MaxAction,
    transport: MaxTransport,
    *,
    now: datetime,
) -> None:
    """Authorize one action at its call boundary, including expiry."""
    require_action_window(record, now=now)
    if record.transport != transport:
        raise PlatformAuthorizationHold("transport_mismatch")
    if action not in record.allowed_actions:
        raise PlatformAuthorizationHold("action_not_allowed")
