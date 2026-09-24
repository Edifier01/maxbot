"""A25: bounded HTTP/WebSocket ingress and trusted proxy behavior."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock


async def _run_http(middleware, *, headers=(), messages=()):
    sent = []
    called = False
    pending = list(messages)

    async def receive():
        if pending:
            return pending.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def app(_scope, _receive, app_send):
        nonlocal called
        called = True
        await app_send({"type": "http.response.start", "status": 200, "headers": []})
        await app_send({"type": "http.response.body", "body": b"ok"})

    scope = {"type": "http", "method": "POST", "headers": list(headers)}
    middleware.app = app
    await middleware(scope, receive, send)
    return called, sent


def test_http_ingress_rejects_declared_oversize_before_route() -> None:
    from app.middleware import IngressLimitsMiddleware

    called, sent = asyncio.run(
        _run_http(
            IngressLimitsMiddleware(AsyncMock(), max_bytes=4, timeout=0.05),
            headers=((b"content-length", b"5"),),
        )
    )
    assert called is False
    assert sent[0]["status"] == 413


def test_http_ingress_rejects_slow_chunked_upload() -> None:
    from app.middleware import IngressLimitsMiddleware

    middleware = IngressLimitsMiddleware(AsyncMock(), max_bytes=4, timeout=0.01)
    sent = []

    async def receive():
        await asyncio.sleep(0.05)
        return {"type": "http.request", "body": b"x", "more_body": False}

    async def send(message):
        sent.append(message)

    async def app(*_args):
        raise AssertionError("slow request reached route")

    middleware.app = app
    asyncio.run(
        middleware(
            {"type": "http", "method": "POST", "headers": []},
            receive,
            send,
        )
    )
    assert sent[0]["status"] == 408


def test_http_ingress_rejects_actual_oversize_chunked_upload() -> None:
    from app.middleware import IngressLimitsMiddleware

    called, sent = asyncio.run(
        _run_http(
            IngressLimitsMiddleware(AsyncMock(), max_bytes=4, timeout=0.05),
            messages=(
                {"type": "http.request", "body": b"abc", "more_body": True},
                {"type": "http.request", "body": b"de", "more_body": False},
            ),
        )
    )
    assert called is False
    assert sent[0]["status"] == 413


def test_mutating_request_origin_must_match_host() -> None:
    from app.middleware import _same_origin_request

    assert _same_origin_request(
        SimpleNamespace(headers={"Origin": "https://panel.example", "Host": "panel.example"})
    )
    assert not _same_origin_request(
        SimpleNamespace(headers={"Origin": "https://evil.example", "Host": "panel.example"})
    )
    assert _same_origin_request(SimpleNamespace(headers={"Host": "panel.example"}))
    assert _same_origin_request(
        SimpleNamespace(
            headers={"Origin": "https://panel.example", "Host": "panel.example:443"}
        )
    )
    assert not _same_origin_request(
        SimpleNamespace(
            headers={"Origin": "https://panel.example", "Host": "panel.example:80"}
        )
    )


def test_public_mutation_is_also_origin_checked(monkeypatch) -> None:
    from app.middleware import ServerAuthMiddleware
    from starlette.requests import Request

    monkeypatch.setattr("app.middleware.is_server_mode", lambda: True)
    middleware = ServerAuthMiddleware(AsyncMock())
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/exit-impersonation",
            "headers": [
                (b"origin", b"https://evil.example"),
                (b"host", b"panel.example"),
            ],
            "query_string": b"",
            "scheme": "https",
            "client": ("203.0.113.10", 1234),
            "server": ("panel.example", 443),
        }
    )
    response = asyncio.run(middleware.dispatch(request, AsyncMock()))
    assert response.status_code == 403


def test_ws_auth_rejects_oversized_first_message(monkeypatch) -> None:
    from app import routes_monitor

    monkeypatch.setattr("app.config.is_server_mode", lambda: True)
    monkeypatch.setattr(routes_monitor.m, "MAX_WS_MESSAGE_BYTES", 16)
    ws = AsyncMock()
    ws.cookies = {}
    ws.receive_text = AsyncMock(
        return_value=json.dumps({"type": "auth", "padding": "x" * 100})
    )
    assert asyncio.run(routes_monitor._authenticate_ws(ws)) is False


def test_ws_connection_limit_rejects_without_waiting(monkeypatch) -> None:
    from app import routes_monitor

    monkeypatch.setattr("app.config.is_server_mode", lambda: True)
    monkeypatch.setattr(routes_monitor, "_WS_CONNECTIONS", asyncio.Semaphore(0))
    ws = AsyncMock()
    asyncio.run(routes_monitor.ws_status(ws))
    ws.close.assert_awaited_once_with(code=4429)
