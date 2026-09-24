"""Persistent external-action hold kept outside restored application data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Literal

from app.config import platform_authorization_file, recovery_hold_file
from app.platform_policy import (
    MaxAction,
    MaxTransport,
    PlatformAuthorizationHold,
    load_authorization_record,
    require_action,
)


_MAX_TEXT = 200


@dataclass(frozen=True, slots=True)
class RecoveryHold:
    schema_version: Literal[1]
    revision: str
    reason: str
    created_at: datetime


class RecoveryHoldActive(RuntimeError):
    """Raised before an external action while recovery is still fenced."""


def _bounded_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("text_type")
    value = value.strip()
    if not value or len(value) > _MAX_TEXT or not value.isprintable():
        raise ValueError("text_invalid")
    return value


def load_recovery_hold(path: Path) -> RecoveryHold | None:
    """Read the control record; malformed or unreadable records fail closed."""
    try:
        exists = path.exists()
    except OSError as exc:
        raise RecoveryHoldActive("recovery_hold_unreadable") from exc
    if not exists:
        return None
    try:
        if not path.is_file():
            raise ValueError("not_a_file")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("schema_version")
        created_at = datetime.fromisoformat(
            _bounded_text(payload["created_at"]).replace("Z", "+00:00")
        )
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at_not_aware")
        return RecoveryHold(
            schema_version=1,
            revision=_bounded_text(payload["revision"]),
            reason=_bounded_text(payload["reason"]),
            created_at=created_at,
        )
    except RecoveryHoldActive:
        raise
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RecoveryHoldActive("recovery_hold_invalid") from exc


def require_recovery_released(path: Path) -> None:
    """Require the external control record to be absent."""
    hold = load_recovery_hold(path)
    if hold is not None:
        raise RecoveryHoldActive("recovery_hold_active")


def require_external_actions_released() -> None:
    """Fail closed before any MAX action while the persistent hold exists."""
    path = recovery_hold_file()
    if path is not None:
        require_recovery_released(path)


def external_actions_status() -> tuple[str, bool]:
    """Return health-safe authorization state without exposing record contents."""
    path = recovery_hold_file()
    if path is not None:
        try:
            hold = load_recovery_hold(path)
        except RecoveryHoldActive:
            return "held", True
        if hold is not None:
            return "held", True
    authorization_path = platform_authorization_file()
    if authorization_path is None:
        return "record_missing", False
    try:
        now = datetime.now(UTC)
        record = load_authorization_record(authorization_path, now=now)
        require_action(record, MaxAction.SEND, MaxTransport.AUTHORIZED_USER_SESSION, now=now)
    except PlatformAuthorizationHold as exc:
        return str(exc), False
    except OSError:
        return "record_unreadable", False
    return "authorized", False
