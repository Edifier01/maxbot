"""Campaign/send must not request MAX SMS when a session is missing."""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _setup_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    monkeypatch.setenv("MAX_DATA", str(tmp_path / "data"))
    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.reset_test_runtime()
    m.init_db()
    return m


def test_session_only_auth_flow_does_not_request_code():
    import main as m

    app = MagicMock()
    app.api.auth.request_code = AsyncMock()

    async def _run():
        with pytest.raises(RuntimeError, match="не запрашивает SMS"):
            await m._SessionOnlyAuthFlow().authenticate(app)

    asyncio.run(_run())
    app.api.auth.request_code.assert_not_called()


def test_send_without_session_does_not_construct_client(tmp_path, monkeypatch):
    m = _setup_db(tmp_path, monkeypatch)
    created: list[object] = []

    class BoomClient:
        def __init__(self, *args, **kwargs):
            created.append(kwargs)
            raise AssertionError("pymax Client must not start without a session")

    fake_pymax = SimpleNamespace(Client=BoomClient, ExtraConfig=lambda **k: object())
    monkeypatch.setitem(__import__("sys").modules, "pymax", fake_pymax)

    async def _run():
        with pytest.raises(RuntimeError, match="не запрашивает SMS"):
            await m._with_client(1, "+79991112233", lambda _c: None)

    asyncio.run(_run())
    assert created == []
    assert m._auth_sessions[m._auth_session_key(1)]["step"] == "idle"


def _fake_started_client():
    class FakeClient:
        def __init__(self, *args, **kwargs):
            self._app = SimpleNamespace(started=True)
            self._on_start = None

        def on_start(self):
            def deco(fn):
                self._on_start = fn
                return fn

            return deco

        async def start(self):
            await self._on_start(self)

        async def stop(self):
            pass

    return FakeClient


def test_send_does_not_set_connecting_auth_step(tmp_path, monkeypatch):
    m = _setup_db(tmp_path, monkeypatch)
    pid = 1
    steps: list[str] = []
    orig = m._set_auth_step

    def spy(profile_id, step, hint=""):
        steps.append(step)
        orig(profile_id, step, hint)

    monkeypatch.setattr(m, "_set_auth_step", spy)
    monkeypatch.setattr(m, "_session_db_has_token", lambda _id: True)
    monkeypatch.setattr(m, "_decrypt_session", lambda _id: None)
    monkeypatch.setattr(m, "_encrypt_session", lambda _id: None)
    monkeypatch.setattr(m, "_session_device_fields", lambda _id: (None, None))
    monkeypatch.setattr(m, "_safe_stop", AsyncMock())
    monkeypatch.setitem(
        __import__("sys").modules,
        "pymax",
        SimpleNamespace(Client=_fake_started_client(), ExtraConfig=lambda **k: object()),
    )
    m._set_auth_step(pid, "idle")
    steps.clear()

    async def _run():
        async def _fn(_c):
            return "ok"

        return await m._with_client(pid, "+79991112233", _fn)

    assert asyncio.run(_run()) == "ok"
    assert "connecting" not in steps
    assert m._auth_sessions[m._auth_session_key(pid)]["step"] == "idle"


def test_send_clears_stale_connecting_step(tmp_path, monkeypatch):
    m = _setup_db(tmp_path, monkeypatch)
    pid = 1
    monkeypatch.setattr(m, "_session_db_has_token", lambda _id: True)
    monkeypatch.setattr(m, "_decrypt_session", lambda _id: None)
    monkeypatch.setattr(m, "_encrypt_session", lambda _id: None)
    monkeypatch.setattr(m, "_session_device_fields", lambda _id: (None, None))
    monkeypatch.setattr(m, "_safe_stop", AsyncMock())
    monkeypatch.setitem(
        __import__("sys").modules,
        "pymax",
        SimpleNamespace(Client=_fake_started_client(), ExtraConfig=lambda **k: object()),
    )
    m._set_auth_step(pid, "connecting")

    async def _run():
        async def _fn(_c):
            return "ok"

        await m._with_client(pid, "+79991112233", _fn)

    asyncio.run(_run())
    assert m._auth_sessions[m._auth_session_key(pid)]["step"] == "idle"
