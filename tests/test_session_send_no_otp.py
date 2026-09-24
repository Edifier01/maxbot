"""Campaign/send must not request MAX SMS when a session is missing."""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.platform_policy import AuthorizationRecord, MaxAction, MaxTransport


def _fixture_authorization_record() -> AuthorizationRecord:
    now = datetime.now(UTC)
    return AuthorizationRecord(
        schema_version=1,
        reference="fixture-session-runtime",
        transport=MaxTransport.AUTHORIZED_USER_SESSION,
        allowed_actions=frozenset({MaxAction.CONNECT}),
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=5),
    )


def _install_fake_runtime(m, monkeypatch) -> None:
    monkeypatch.setattr(
        m,
        "_platform_authorization_record",
        _fixture_authorization_record,
    )
    monkeypatch.setattr(m, "_ensure_session_identity", AsyncMock(return_value=None))
    monkeypatch.setattr(
        m,
        "_build_pymax_client",
        lambda **_kwargs: _fake_connected_client()(),
    )


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
    encrypt = MagicMock()

    class BoomClient:
        def __init__(self, *args, **kwargs):
            created.append(kwargs)
            raise AssertionError("pymax Client must not start without a session")

    fake_pymax = SimpleNamespace(Client=BoomClient, ExtraConfig=lambda **k: object())
    monkeypatch.setitem(__import__("sys").modules, "pymax", fake_pymax)
    monkeypatch.setattr(m, "_decrypt_session", lambda _id: None)
    monkeypatch.setattr(m, "_encrypt_session", encrypt)

    async def _run():
        with pytest.raises(RuntimeError, match="не запрашивает SMS"):
            await m._with_client(1, "+79991112233", lambda _c: None)

    asyncio.run(_run())
    assert created == []
    encrypt.assert_called_once_with(1)
    assert m._auth_sessions[m._auth_session_key(1)]["step"] == "idle"


def test_stop_failure_cannot_skip_session_reseal(tmp_path, monkeypatch):
    m = _setup_db(tmp_path, monkeypatch)
    _install_fake_runtime(m, monkeypatch)
    encrypt = MagicMock()
    monkeypatch.setattr(m, "_session_db_has_token", lambda _id: True)
    monkeypatch.setattr(m, "_decrypt_session", lambda _id: None)
    monkeypatch.setattr(m, "_encrypt_session", encrypt)
    monkeypatch.setattr(m, "_safe_stop", AsyncMock(side_effect=OSError("stop failed")))

    async def _run():
        async def _fn(_c):
            return "ok"

        await m._with_client(1, "+79991112233", _fn)

    with pytest.raises(OSError, match="stop failed"):
        asyncio.run(_run())
    encrypt.assert_called_once_with(1)


def _fake_connected_client():
    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.connected = False

        async def connect(self):
            self.connected = True

        async def stop(self):
            pass

    return FakeClient


def test_send_does_not_set_connecting_auth_step(tmp_path, monkeypatch):
    m = _setup_db(tmp_path, monkeypatch)
    _install_fake_runtime(m, monkeypatch)
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
    monkeypatch.setattr(m, "_safe_stop", AsyncMock())
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
    _install_fake_runtime(m, monkeypatch)
    pid = 1
    monkeypatch.setattr(m, "_session_db_has_token", lambda _id: True)
    monkeypatch.setattr(m, "_decrypt_session", lambda _id: None)
    monkeypatch.setattr(m, "_encrypt_session", lambda _id: None)
    monkeypatch.setattr(m, "_safe_stop", AsyncMock())
    m._set_auth_step(pid, "connecting")

    async def _run():
        async def _fn(_c):
            return "ok"

        await m._with_client(pid, "+79991112233", _fn)

    asyncio.run(_run())
    assert m._auth_sessions[m._auth_session_key(pid)]["step"] == "idle"


def test_runtime_client_manager_serializes_real_with_client_calls(tmp_path, monkeypatch):
    m = _setup_db(tmp_path, monkeypatch)
    _install_fake_runtime(m, monkeypatch)
    monkeypatch.setattr(m, "_session_db_has_token", lambda _id: True)
    monkeypatch.setattr(m, "_decrypt_session", lambda _id: None)
    monkeypatch.setattr(m, "_encrypt_session", lambda _id: None)
    monkeypatch.setattr(m, "_safe_stop", AsyncMock())

    async def _run():
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def _first(_client):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return "first"

        async def _second(_client):
            nonlocal calls
            calls += 1
            return "second"

        first = asyncio.create_task(m._with_client(1, "+79991112233", _first))
        await entered.wait()
        second = asyncio.create_task(m._with_client(1, "+79991112233", _second))
        await asyncio.sleep(0)
        assert calls == 1
        release.set()
        assert await first == "first"
        assert await second == "second"

    asyncio.run(_run())
