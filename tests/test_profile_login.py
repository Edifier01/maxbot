"""Mocked MAX profile login HTTP happy path."""

from __future__ import annotations

import importlib
import time
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

_LOGIN_PHONE = "+79990014401"


@pytest.fixture
def login_app(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.init_db()
    yield m
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
