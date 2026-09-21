"""T03 contract tests: source-aware errors never turn proxy failures into bans."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path


def test_proxy_auth_failure_is_not_a_max_ban() -> None:
    from app.services.errors import classify_exception

    info = classify_exception(
        RuntimeError("proxy authentication failed"),
        source="proxy",
        stage="connect",
        outcome="rejected",
    )

    assert info.code == "PROXY_AUTH_FAILED"
    assert info.source == "proxy"
    assert info.recommended_action != "STOP_TENANT"
    assert info.session_preserved is True
    assert info.retryable is False


def test_proxy_connection_block_does_not_stop_tenant() -> None:
    from app.services.errors import classify_exception

    info = classify_exception(
        ConnectionError("connection blocked by proxy"),
        source="proxy",
        stage="connect",
        outcome="rejected",
    )

    assert info.code == "PROXY_CONNECT_FAILED"
    assert info.recommended_action != "STOP_TENANT"
    assert info.session_preserved is True


def test_confirmed_max_ban_stops_tenant() -> None:
    from app.services.errors import classify_exception

    info = classify_exception(
        RuntimeError("account banned"),
        source="max",
        stage="send",
        outcome="rejected",
    )

    assert info.code == "MAX_ACCOUNT_BANNED"
    assert info.recommended_action == "STOP_TENANT"
    assert info.retryable is False


def test_unknown_mutating_outcome_is_never_automatically_retryable() -> None:
    from app.services.errors import classify_exception

    info = classify_exception(
        TimeoutError("request timed out"),
        source="max",
        stage="send",
        outcome="unknown",
        operation_id="op-1",
        attempt_id="attempt-1",
    )

    assert info.code == "SEND_OUTCOME_UNKNOWN"
    assert info.retryable is False
    assert info.operation_id == "op-1"
    assert info.attempt_id == "attempt-1"
    assert info.recommended_action == "RECONCILE_BEFORE_RETRY"


def test_safe_error_contains_no_password_otp_or_token() -> None:
    from app.services.errors import classify_exception, redact_error

    sentinel_values = ("Password-Secret-123", "123456", "token-secret-xyz")
    exc = RuntimeError("password=Password-Secret-123 otp=123456 token=token-secret-xyz")
    info = classify_exception(exc, source="max", stage="login", outcome="rejected")
    public = asdict(redact_error(info))
    rendered = repr(public)

    for sentinel in sentinel_values:
        assert sentinel not in rendered
    assert public["safe_message"]


def test_explicit_source_wins_over_untrusted_exception_text() -> None:
    from app.services.errors import classify_exception

    info = classify_exception(
        RuntimeError("MAX account blocked"),
        source="proxy",
        stage="connect",
        outcome="rejected",
    )

    assert info.code in {"PROXY_AUTH_FAILED", "PROXY_CONNECT_FAILED"}
    assert info.code != "MAX_ACCOUNT_BANNED"


def test_frontend_has_safe_structured_error_map() -> None:
    source = Path("static/js/index.js").read_text(encoding="utf-8")
    admin_source = Path("static/js/admin.js").read_text(encoding="utf-8")

    assert "MAX_ACCOUNT_BANNED" in source
    assert "SEND_OUTCOME_UNKNOWN" in source
    assert "NETWORK_UNAVAILABLE" in source

    # The server catalogue is authoritative for codes not duplicated in the
    # small legacy fallback maps. Never discard its already-redacted message.
    assert "detail.safe_message" in source
    assert "detail.safe_message" in admin_source
