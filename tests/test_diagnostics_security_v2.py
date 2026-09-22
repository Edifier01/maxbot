"""T26 diagnostics are scoped, redacted, and read-only."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest
from fastapi import HTTPException


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE profiles (id INTEGER PRIMARY KEY, phone TEXT, status TEXT, last_error TEXT)")
    connection.execute(
        "INSERT INTO profiles VALUES (1, '+79000000000', 'pending', 'safe error')"
    )
    connection.commit()
    return connection


def test_diagnostic_view_redacts_auth_queues_and_secrets(monkeypatch) -> None:
    from app.routes_diagnostics import get_auth_attempt_diagnostic
    from app.runtime import main as runtime

    connection = _connection()
    monkeypatch.setattr(runtime, "_is_server_mode", lambda: False)
    monkeypatch.setattr(runtime, "_conn", lambda: connection)
    runtime._auth_sessions[1] = {
        "step": "waiting_sms",
        "hint": "secret cloud password hint",
        "sms_q": object(),
        "pwd_q": object(),
        "token": "jwt-secret",
    }
    try:
        result = asyncio.run(get_auth_attempt_diagnostic("profile-1"))
    finally:
        runtime._auth_sessions.pop(1, None)

    assert result["attempt_id"] == "profile-1"
    assert result["phone"] == "+7900••••••00"
    assert result["auth_step"] == "waiting_sms"
    assert "hint" not in result
    assert "sms_q" not in result
    assert "pwd_q" not in result
    assert "jwt-secret" not in str(result)


def test_diagnostic_view_returns_404_for_unknown_attempt(monkeypatch) -> None:
    from app.routes_diagnostics import get_auth_attempt_diagnostic
    from app.runtime import main as runtime

    connection = _connection()
    monkeypatch.setattr(runtime, "_is_server_mode", lambda: False)
    monkeypatch.setattr(runtime, "_conn", lambda: connection)
    with pytest.raises(HTTPException) as error:
        asyncio.run(get_auth_attempt_diagnostic("profile-999"))
    assert error.value.status_code == 404
