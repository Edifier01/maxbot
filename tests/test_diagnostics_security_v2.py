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


def test_diagnostic_id_from_another_tenant_is_indistinguishable_from_missing(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")

    import importlib

    import app.config as config

    importlib.reload(config)
    import main as runtime_main

    importlib.reload(runtime_main)
    monkeypatch.setattr(runtime_main, "ROOT", tmp_path)
    runtime_main._refresh_data_paths()

    from app.tenant import tenant_scope
    from app.tenant_init import ensure_tenant_data

    for tenant_id in (1, 2):
        ensure_tenant_data(tmp_path, tenant_id)
        with tenant_scope(tenant_id=tenant_id, role="user"):
            if not runtime_main._db_path().exists():
                runtime_main.init_db()
            with runtime_main._conn() as connection:
                profile_id = 99 if tenant_id == 1 else 1
                connection.execute(
                    "INSERT INTO profiles (id, phone, status) VALUES (?, ?, ?)",
                    (profile_id, f"+790000000{tenant_id}", "pending"),
                )

    from app.routes_diagnostics import get_auth_attempt_diagnostic
    from app import sqlite_backend

    try:
        with tenant_scope(tenant_id=2, role="user"):
            with pytest.raises(HTTPException) as foreign:
                asyncio.run(get_auth_attempt_diagnostic("profile-99"))
            with pytest.raises(HTTPException) as missing:
                asyncio.run(get_auth_attempt_diagnostic("profile-999"))
    finally:
        sqlite_backend.reset_connections()

    assert foreign.value.status_code == missing.value.status_code == 404
    assert foreign.value.detail == missing.value.detail == "Попытка не найдена"


def test_auth_attempt_export_is_user_scoped_and_has_only_approved_fields(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from app.routes_diagnostics import export_current_auth_attempt
    from app.runtime import main as runtime
    from app.tenant import clear_context, tenant_scope

    connection = _connection()
    attempt = SimpleNamespace(
        attempt_id="attempt-current-123",
        auth_step="waiting_sms",
        error_code=None,
    )
    monkeypatch.setattr(runtime, "_is_server_mode", lambda: True)
    monkeypatch.setattr(runtime, "_conn", lambda: connection)
    monkeypatch.setattr(runtime, "_current_auth_attempt", lambda _profile_id: attempt)
    try:
        with tenant_scope(user_id=7, tenant_id=3, role="user"):
            preview = asyncio.run(
                export_current_auth_attempt(1, "attempt-current-123", download=False)
            )
            assert set(preview) == {
                "attempt_id",
                "phone",
                "status",
                "auth_step",
                "next_action",
                "has_error",
                "retention",
            }
            assert preview == {
                "attempt_id": "attempt-current-123",
                "phone": "+7900••••••00",
                "status": "pending",
                "auth_step": "waiting_sms",
                "next_action": "submit_code",
                "has_error": True,
                "retention": "metadata_only",
            }
            assert all(
                forbidden not in repr(preview).lower()
                for forbidden in ("request_id", "operation_id", "latency", "safe error")
            )

            response = asyncio.run(
                export_current_auth_attempt(1, "attempt-current-123", download=True)
            )
            assert response.headers["content-disposition"].startswith("attachment;")
            assert response.media_type == "application/json"
    finally:
        clear_context()


def test_auth_attempt_export_rejects_admin_and_non_current_attempt(monkeypatch) -> None:
    from types import SimpleNamespace

    from fastapi import HTTPException
    from app.routes_diagnostics import export_current_auth_attempt
    from app.runtime import main as runtime
    from app.tenant import tenant_scope

    connection = _connection()
    monkeypatch.setattr(runtime, "_is_server_mode", lambda: True)
    monkeypatch.setattr(runtime, "_conn", lambda: connection)
    monkeypatch.setattr(
        runtime,
        "_current_auth_attempt",
        lambda _profile_id: SimpleNamespace(
            attempt_id="attempt-current", auth_step="waiting_sms", error_code=None
        ),
    )
    with tenant_scope(user_id=1, tenant_id=3, role="admin"):
        with pytest.raises(HTTPException) as forbidden:
            asyncio.run(
                export_current_auth_attempt(1, "attempt-current", download=False)
            )
    with tenant_scope(user_id=7, tenant_id=3, role="user"):
        with pytest.raises(HTTPException) as stale:
            asyncio.run(
                export_current_auth_attempt(1, "attempt-old", download=False)
            )
    assert forbidden.value.status_code == 403
    assert stale.value.status_code == 404


def test_prometheus_metric_labels_exclude_profile_and_secret_identifiers(
    monkeypatch,
) -> None:
    from app.routes_monitor import prometheus_metrics
    from app.runtime import main as runtime_main

    monkeypatch.setattr(runtime_main, "_is_server_mode", lambda: False)
    monkeypatch.setattr(runtime_main, "REDIS_URL", "")

    response = asyncio.run(prometheus_metrics())
    body = response.body.decode("utf-8")
    sensitive = (
        "+79001234567",
        "socks5://operator:private@proxy.example:1080",
        "attempt-00000000-0000-4000-8000-000000000001",
    )

    label_lines = [line for line in body.splitlines() if "{" in line]
    assert label_lines
    assert all(line.startswith("max_sender_info{") for line in label_lines)
    for line in label_lines:
        label_text = line.split("{", 1)[1].split("}", 1)[0]
        labels = [part.split("=", 1)[0] for part in label_text.split(",")]
        assert set(labels) <= {"version", "db"}
    assert all(value not in body for value in sensitive)
