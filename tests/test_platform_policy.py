import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.platform_policy import (
    MaxAction,
    MaxTransport,
    PlatformAuthorizationHold,
    load_authorization_record,
    require_action,
)


NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def write_record(
    tmp_path: Path,
    *,
    allowed_actions: tuple[str, ...] = ("send",),
    valid_from: str = "2026-09-20T00:00:00Z",
    valid_until: str = "2026-09-21T12:00:00Z",
) -> Path:
    path = tmp_path / "platform-authorization.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "reference": "MAX-COMPANY-PERMISSION-2026-001",
                "transport": "authorized_user_session",
                "allowed_actions": list(allowed_actions),
                "valid_from": valid_from,
                "valid_until": valid_until,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_missing_record_blocks_send(tmp_path: Path) -> None:
    with pytest.raises(PlatformAuthorizationHold, match="record_missing"):
        load_authorization_record(tmp_path / "missing.json", now=NOW)


def test_expired_record_blocks_every_action(tmp_path: Path) -> None:
    path = write_record(tmp_path, valid_until="2026-09-20T11:59:59Z")
    with pytest.raises(PlatformAuthorizationHold, match="record_expired"):
        load_authorization_record(path, now=NOW)


def test_malformed_record_blocks_send(tmp_path: Path) -> None:
    path = tmp_path / "platform-authorization.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(PlatformAuthorizationHold, match="record_malformed"):
        load_authorization_record(path, now=NOW)


def test_future_record_blocks_send(tmp_path: Path) -> None:
    path = write_record(tmp_path, valid_from="2026-09-20T12:00:01Z")
    with pytest.raises(PlatformAuthorizationHold, match="record_expired"):
        load_authorization_record(path, now=NOW)


def test_transport_mismatch_blocks_action(tmp_path: Path) -> None:
    record = load_authorization_record(write_record(tmp_path), now=NOW)
    with pytest.raises(PlatformAuthorizationHold, match="transport_mismatch"):
        require_action(record, MaxAction.SEND, MaxTransport.FAKE, now=NOW)


def test_allowed_send_action_is_authorized(tmp_path: Path) -> None:
    record = load_authorization_record(write_record(tmp_path), now=NOW)
    require_action(
        record,
        MaxAction.SEND,
        MaxTransport.AUTHORIZED_USER_SESSION,
        now=NOW,
    )


def test_send_permission_does_not_authorize_join(tmp_path: Path) -> None:
    record = load_authorization_record(
        write_record(tmp_path, allowed_actions=("send",)), now=NOW
    )
    with pytest.raises(PlatformAuthorizationHold, match="action_not_allowed"):
        require_action(
            record,
            MaxAction.JOIN_DESTINATION,
            MaxTransport.AUTHORIZED_USER_SESSION,
            now=NOW,
        )
