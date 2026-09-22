"""T26 WebSocket origin gate is fail-closed in server mode."""

from __future__ import annotations

from types import SimpleNamespace


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
