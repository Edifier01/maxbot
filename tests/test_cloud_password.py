"""Cloud password (2FA) during MAX profile login."""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock


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


def test_submit_cloud_password_api(tmp_path, monkeypatch):
    m = _setup_db(tmp_path, monkeypatch)
    with m._conn() as c:
        c.execute(
            "INSERT INTO profiles (phone, label, status) VALUES (?, ?, ?)",
            ("+79991112233", "t", m.ProfileStatus.PENDING),
        )
        pid = c.execute("SELECT id FROM profiles WHERE phone=?", ("+79991112233",)).fetchone()["id"]

    from starlette.testclient import TestClient

    with TestClient(m.app) as client:
        sess = m._ensure_auth_session(pid)
        m._set_auth_step(pid, "waiting_cloud_password", "hint123")
        r = client.post(f"/api/profiles/{pid}/password", json={"code": "secret-cloud"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    assert sess["pwd_q"].get_nowait() == "secret-cloud"
    assert m._auth_sessions[m._auth_session_key(pid)]["step"] == "verifying_password"


def test_sms_auth_flow_password_challenge(monkeypatch):
    import main as m

    m.reset_test_runtime()
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setattr(m, "get_setting", lambda key: "3" if key == "password_max_attempts" else "")

    profile_id = 7
    pwd_q: asyncio.Queue[str] = asyncio.Queue()
    sms_q: asyncio.Queue[str] = asyncio.Queue()

    flow = m._AppSmsAuthFlow(
        m._QueueSmsProvider(sms_q, profile_id),
        m._QueuePasswordProvider(pwd_q, profile_id),
        profile_id,
    )

    challenge = SimpleNamespace(track_id="track-1", hint="☁")
    send_result = SimpleNamespace(
        login_token=None,
        password_challenge=challenge,
        register_token=None,
    )
    check_response = SimpleNamespace(error=None, login_token="tok-ok")

    app = MagicMock()
    app.config.phone = "+79991112233"
    app.api.auth.request_code = AsyncMock(return_value=SimpleNamespace(token="sms-tok"))
    app.api.auth.send_code = AsyncMock(return_value=send_result)
    app.api.auth.check_password = AsyncMock(return_value=check_response)

    async def _run():
        await sms_q.put("1234")
        await pwd_q.put("cloud-pass")
        return await flow.authenticate(app)

    from pymax.auth.models import AuthResult

    result = asyncio.run(_run())
    assert isinstance(result, AuthResult)
    assert result.token == "tok-ok"
    app.api.auth.check_password.assert_awaited_once_with("track-1", "cloud-pass")
