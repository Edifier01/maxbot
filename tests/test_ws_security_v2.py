"""T26 WebSocket origin gate is fail-closed in server mode."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch


def test_server_websocket_requires_matching_origin(monkeypatch) -> None:
    from app.routes_monitor import _ws_origin_allowed

    monkeypatch.setattr("app.config.is_server_mode", lambda: True)
    assert _ws_origin_allowed(SimpleNamespace(headers={"origin": "https://panel.example", "host": "panel.example"}))
    assert not _ws_origin_allowed(SimpleNamespace(headers={"origin": "https://evil.example", "host": "panel.example"}))
    assert not _ws_origin_allowed(SimpleNamespace(headers={"host": "panel.example"}))


def test_desktop_websocket_keeps_pin_flow_compatible(monkeypatch) -> None:
    from app.routes_monitor import _ws_origin_allowed

    monkeypatch.setattr("app.config.is_server_mode", lambda: False)
    assert _ws_origin_allowed(SimpleNamespace(headers={}))


def test_ws_does_not_send_another_status_after_shared_jwt_revocation(monkeypatch) -> None:
    from app import auth, routes_monitor

    monkeypatch.setattr("app.config.is_server_mode", lambda: True)
    payload = {
        "sub": "1",
        "role": "user",
        "tenant_id": 1,
        "jti": "ws-cross-worker-revoke",
        "tv": 0,
    }
    revoked = False
    runtime = SimpleNamespace(shutting_down=False)

    class FixtureWebSocket:
        headers = {"origin": "https://panel.example", "host": "panel.example"}
        cookies = {"max_token": "fixture-jwt"}

        def __init__(self) -> None:
            self.messages = []
            self.close_codes = []

        async def accept(self) -> None:
            return None

        async def receive_text(self) -> str:
            return '{"type":"auth"}'

        async def send_json(self, value) -> None:
            self.messages.append(value)
            if len(self.messages) == 2:
                runtime.shutting_down = True

        async def close(self, *, code=None) -> None:
            self.close_codes.append(code)

    ws = FixtureWebSocket()

    async def revoke_between_status_reads(_delay: float) -> None:
        nonlocal revoked
        revoked = True

    auth.clear_session_cache()
    try:
        with patch("app.auth_epoch.current_epoch", return_value=0.0), patch(
            "app.auth.decode_token", return_value=payload
        ), patch(
            "app.db_pg.is_token_revoked", side_effect=lambda _jti: revoked
        ), patch(
            "app.db_pg.get_user_by_id", return_value={"id": 1}
        ), patch(
            "app.db_pg.get_tenant", return_value={"id": 1, "token_version": 0}
        ), patch.object(
            routes_monitor.m, "RUNTIME", runtime
        ), patch.object(
            routes_monitor.m, "_build_status_payload", return_value={"summary": "fixture"}
        ), patch.object(
            routes_monitor.m, "_try_legacy_unlock", return_value=None
        ), patch(
            "app.routes_monitor.asyncio.sleep", new=revoke_between_status_reads
        ):
            assert auth.cached_validate_token_session(payload) is None
            asyncio.run(routes_monitor.ws_status(ws))
    finally:
        auth.clear_session_cache()

    assert ws.messages == [{"summary": "fixture"}]
    assert ws.close_codes == [4401]
