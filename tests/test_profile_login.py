"""Mocked MAX profile login HTTP happy path."""

from __future__ import annotations

import asyncio
from contextlib import closing
import importlib
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

_LOGIN_PHONE = "+79990014401"


@pytest.fixture
def login_app(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    monkeypatch.setenv("MAX_DATA", str(tmp_path / "data"))
    import app.config as cfg
    import app.sqlite_backend as sqlite_backend

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    sqlite_backend.reset_connections()
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.init_db()
    yield m
    sqlite_backend.reset_connections()
    monkeypatch.undo()
    importlib.reload(cfg)
    importlib.reload(m)


def test_profile_login_happy_path(login_app):
    m = login_app
    with m._conn() as c:
        c.execute(
            "INSERT INTO profiles (phone, label, status) VALUES (?, ?, ?)",
            (_LOGIN_PHONE, "t", m.ProfileStatus.PENDING),
        )
        pid = c.execute("SELECT id FROM profiles WHERE phone=?", (_LOGIN_PHONE,)).fetchone()["id"]

    m._login_max = AsyncMock(return_value=424242)

    with TestClient(m.app) as client:
        r = client.post(f"/api/profiles/{pid}/login")
        assert r.status_code == 200
        assert r.json()["auth_step"] == "connecting"

        task = m._login_tasks[m._auth_session_key(pid)]
        deadline = time.monotonic() + 2
        while not task.done() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert task.done()
        assert task.exception() is None

    with m._conn() as c:
        row = c.execute("SELECT status FROM profiles WHERE id=?", (pid,)).fetchone()
    assert row["status"] == m.ProfileStatus.ACTIVE
    assert m._auth_sessions[m._auth_session_key(pid)]["step"] == "idle"


def test_http_login_proxy_failure_preserves_encrypted_identity_without_code_or_fresh_relogin(
    login_app, monkeypatch
):
    m = login_app
    from app.platform_policy import AuthorizationRecord, MaxAction, MaxTransport

    with m._conn() as connection:
        connection.execute(
            "INSERT INTO profiles (phone, label, status) VALUES (?, ?, ?)",
            (_LOGIN_PHONE, "saved-session", m.ProfileStatus.PENDING),
        )
        profile_id = int(
            connection.execute(
                "SELECT id FROM profiles WHERE phone=?", (_LOGIN_PHONE,)
            ).fetchone()["id"]
        )

    session_dir = m._session_dir(profile_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    session_db = session_dir / "session.db"
    with closing(sqlite3.connect(session_db)) as connection, connection:
        connection.execute(
            "CREATE TABLE sessions (token TEXT NOT NULL PRIMARY KEY, "
            "device_id TEXT NOT NULL, phone TEXT NOT NULL, "
            "mt_instance_id TEXT NOT NULL DEFAULT '', "
            "chats_sync INTEGER NOT NULL DEFAULT -1, "
            "contacts_sync INTEGER NOT NULL DEFAULT -1, "
            "drafts_sync INTEGER NOT NULL DEFAULT -1, "
            "presence_sync INTEGER NOT NULL DEFAULT -1, "
            "config_hash TEXT NOT NULL DEFAULT '')"
        )
        connection.execute(
            "INSERT INTO sessions (token, device_id, phone, mt_instance_id) "
            "VALUES (?, ?, ?, ?)",
            (
                "fixture-auth-token",
                "device-http-stable",
                _LOGIN_PHONE,
                "instance-http-stable",
            ),
        )
    m._ensure_vault_unlocked()
    asyncio.run(m._ensure_session_identity(session_dir, "session.db"))
    m._encrypt_session(profile_id)

    def read_identity() -> tuple[object, ...]:
        m._decrypt_session(profile_id)
        try:
            with closing(sqlite3.connect(session_db)) as connection, connection:
                return connection.execute(
                    "SELECT token, device_id, phone, mt_instance_id, user_agent "
                    "FROM sessions"
                ).fetchone()
        finally:
            m._encrypt_session(profile_id)

    original_identity = read_identity()
    monkeypatch.setattr(
        m,
        "_platform_authorization_record",
        lambda: AuthorizationRecord(
            schema_version=1,
            reference="http-login-fault-fixture",
            transport=MaxTransport.AUTHORIZED_USER_SESSION,
            allowed_actions=frozenset({MaxAction.CONNECT}),
            valid_from=datetime.now(UTC) - timedelta(minutes=1),
            valid_until=datetime.now(UTC) + timedelta(minutes=5),
        ),
    )

    request_code_calls: list[str] = []
    connect_calls: list[str] = []

    class FakeAuthAPI:
        async def request_code(self, phone: str):
            request_code_calls.append(phone)
            raise AssertionError("proxy failure must happen before request_code")

    class FakeClient:
        me = SimpleNamespace(contact=SimpleNamespace(id=424242))

        def __init__(self, **kwargs):
            self.config = kwargs
            self.api = SimpleNamespace(auth=FakeAuthAPI())

        async def connect(self):
            connect_calls.append("connect")
            raise ConnectionError("fixture proxy connection refused")

        async def stop(self):
            return None

    monkeypatch.setattr(m, "_build_pymax_client", lambda **kwargs: FakeClient(**kwargs))
    fresh_relogin_calls: list[int] = []
    original_stage = m._stage_session_for_reauth

    def observe_fresh_relogin(staged_profile_id: int):
        fresh_relogin_calls.append(int(staged_profile_id))
        return original_stage(staged_profile_id)

    monkeypatch.setattr(m, "_stage_session_for_reauth", observe_fresh_relogin)

    with TestClient(m.app) as client:
        started = client.post(f"/api/profiles/{profile_id}/login?request_id=proxy-fixture")
        assert started.status_code == 200
        attempt_id = started.json()["attempt_id"]

        task = m._login_tasks[m._auth_session_key(profile_id)]
        deadline = time.monotonic() + 3
        while not task.done() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert task.done()
        assert task.exception() is None

        terminal = client.get(
            f"/api/profiles/{profile_id}/auth-attempts/{attempt_id}"
        )
        assert terminal.status_code == 200
        assert terminal.json()["auth_stage"] == "error"

    with m._conn() as connection:
        status = connection.execute(
            "SELECT status FROM profiles WHERE id=?", (profile_id,)
        ).fetchone()["status"]
    assert status != m.ProfileStatus.BANNED
    assert connect_calls == ["connect"]
    assert request_code_calls == []
    assert fresh_relogin_calls == []
    assert read_identity() == original_identity
