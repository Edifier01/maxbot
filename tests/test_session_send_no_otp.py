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
    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
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
