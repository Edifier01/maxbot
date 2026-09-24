"""Cloud password (2FA) during MAX profile login."""

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


def test_submit_cloud_password_api(tmp_path, monkeypatch):
    m = _setup_db(tmp_path, monkeypatch)
    try:
        with m._conn() as c:
            c.execute(
                "INSERT INTO profiles (phone, label, status) VALUES (?, ?, ?)",
                ("+79991112233", "t", m.ProfileStatus.PENDING),
            )
            pid = c.execute("SELECT id FROM profiles WHERE phone=?", ("+79991112233",)).fetchone()["id"]

        from app.routes_models import CodeIn
        from app.routes_profiles import submit_password

        sess = m._ensure_auth_session(pid)
        attempt, _ = m._start_auth_attempt(
            pid, group_id=None, fresh=True, request_id="password-start"
        )
        waiting_code = m._auth_attempts().waiting_code(
            "local", pid, attempt_id=attempt.attempt_id
        )
        m._persist_auth_attempt(waiting_code)
        m._sync_auth_attempt_view(waiting_code)
        verifying_code = m._submit_auth_code(
            pid,
            attempt_id=waiting_code.attempt_id,
            revision=waiting_code.revision,
            request_id="code-submit",
        )
        waiting_password = m._auth_attempts().waiting_password(
            "local", pid, attempt_id=attempt.attempt_id, hint="hint123"
        )
        m._persist_auth_attempt(waiting_password)
        m._sync_auth_attempt_view(waiting_password)
        result = asyncio.run(
            submit_password(
                pid,
                CodeIn(
                    code="secret-cloud",
                    attempt_id=waiting_password.attempt_id,
                    revision=waiting_password.revision,
                    request_id="password-submit",
                ),
            )
        )
        assert result["ok"] is True

        assert sess["pwd_q"].get_nowait() == "secret-cloud"
        assert m._auth_sessions[m._auth_session_key(pid)]["step"] == "verifying_password"
        with m._conn() as c:
            metadata = repr(c.execute("SELECT * FROM auth_attempts").fetchall())
        assert "secret-cloud" not in metadata
    finally:
        monkeypatch.undo()
        import app.config as cfg

        importlib.reload(cfg)
        importlib.reload(m)


def test_password_submission_rejects_stale_revision_and_deduplicates_queue(
    tmp_path, monkeypatch
):
    m = _setup_db(tmp_path, monkeypatch)
    try:
        with m._conn() as c:
            c.execute(
                "INSERT INTO profiles (phone, label, status) VALUES (?, ?, ?)",
                ("+79991112234", "t", m.ProfileStatus.PENDING),
            )
            pid = c.execute(
                "SELECT id FROM profiles WHERE phone=?", ("+79991112234",)
            ).fetchone()["id"]

        from fastapi import HTTPException

        from app.routes_models import CodeIn
        from app.routes_profiles import submit_password

        attempt, _ = m._start_auth_attempt(
            pid, group_id=None, fresh=True, request_id="password-start"
        )
        waiting_code = m._auth_attempts().waiting_code(
            "local", pid, attempt_id=attempt.attempt_id
        )
        m._persist_auth_attempt(waiting_code)
        verifying_code = m._submit_auth_code(
            pid,
            attempt_id=waiting_code.attempt_id,
            revision=waiting_code.revision,
            request_id="code-submit",
        )
        waiting_password = m._auth_attempts().waiting_password(
            "local", pid, attempt_id=verifying_code.attempt_id, hint="hint"
        )
        m._persist_auth_attempt(waiting_password)
        m._sync_auth_attempt_view(waiting_password)

        with pytest.raises(HTTPException) as stale:
            asyncio.run(
                submit_password(
                    pid,
                    CodeIn(
                        code="  literal  ",
                        attempt_id=waiting_password.attempt_id,
                        revision=waiting_password.revision - 1,
                        request_id="stale",
                    ),
                )
            )
        assert stale.value.status_code == 409
        assert waiting_password.revision == m._auth_sessions[
            m._auth_session_key(pid)
        ]["revision"]

        payload = CodeIn(
            code="  literal  ",
            attempt_id=waiting_password.attempt_id,
            revision=waiting_password.revision,
            request_id="password-submit-once",
        )
        first = asyncio.run(submit_password(pid, payload))
        repeated = asyncio.run(submit_password(pid, payload))
        assert first["revision"] == repeated["revision"]
        assert m._auth_sessions[m._auth_session_key(pid)]["pwd_q"].get_nowait() == (
            "  literal  "
        )
        with pytest.raises(asyncio.QueueEmpty):
            m._auth_sessions[m._auth_session_key(pid)]["pwd_q"].get_nowait()
        with m._conn() as c:
            metadata = repr(c.execute("SELECT * FROM auth_attempts").fetchall())
        assert "literal" not in metadata
    finally:
        monkeypatch.undo()
        import app.config as cfg

        importlib.reload(cfg)
        importlib.reload(m)


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

    pytest.importorskip("pymax")
    from pymax.auth.models import AuthResult

    result = asyncio.run(_run())
    assert isinstance(result, AuthResult)
    assert result.token == "tok-ok"
    app.api.auth.check_password.assert_awaited_once_with("track-1", "cloud-pass")
