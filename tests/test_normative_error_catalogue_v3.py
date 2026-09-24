"""Normative error-catalogue coverage for the local, non-live boundary."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.services.errors import ERROR_CODES, ErrorInfo, redact_error


ROOT = Path(__file__).resolve().parents[1]


def _documented_actions() -> dict[str, str]:
    actions: dict[str, str] = {}
    for line in (ROOT / "docs/ui-ux-contract.md").read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| Code"):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) == 2 and parts[0] and parts[1] and parts[0] != "---":
            actions[parts[0]] = parts[1]
    return actions


def test_all_catalogue_codes_have_documented_safe_actions() -> None:
    actions = _documented_actions()

    assert len(ERROR_CODES) == 66
    assert set(actions) == set(ERROR_CODES)

    for code in sorted(ERROR_CODES):
        info = ErrorInfo(
            code=code,
            source="http",
            stage="dashboard",
            safe_message="raw-secret-message",
            retryable=True,
            retry_after_at="raw-secret-retry-after",
            session_preserved=True,
            request_id="request-1",
            attempt_id="attempt-1",
            operation_id="operation-1",
            recommended_action="raw-secret-action",
        )
        safe = redact_error(info)

        assert safe.code == code
        assert safe.safe_message
        assert any("а" <= char.lower() <= "я" for char in safe.safe_message)
        assert safe.recommended_action == actions[code]
        assert "raw-secret" not in repr(safe)


def test_rate_limit_deadline_is_bounded_and_timezone_aware() -> None:
    valid = ErrorInfo(
        code="MAX_RATE_LIMIT",
        source="max",
        stage="send",
        safe_message="ignored",
        retryable=False,
        retry_after_at="2026-09-20T12:00:00Z",
        session_preserved=True,
        request_id=None,
        attempt_id=None,
        operation_id=None,
        recommended_action="ignored",
    )
    invalid = replace(valid, retry_after_at="not-a-deadline")

    assert redact_error(valid).retry_after_at == "2026-09-20T12:00:00Z"
    assert redact_error(invalid).retry_after_at is None


def test_unknown_mutating_outcome_remains_reconciliation_only() -> None:
    info = ErrorInfo(
        code="SEND_OUTCOME_UNKNOWN",
        source="max",
        stage="send",
        safe_message="ignored",
        retryable=True,
        retry_after_at=None,
        session_preserved=True,
        request_id="request-1",
        attempt_id="attempt-1",
        operation_id="operation-1",
        recommended_action="ignored",
    )

    safe = redact_error(info)

    assert safe.retryable is False
    assert safe.recommended_action == "RECONCILE_BEFORE_RETRY"
