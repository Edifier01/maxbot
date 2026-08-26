"""Wave 2 (H-1..H-4): rate limit cleanup, session cache, proxy validation."""

from __future__ import annotations

import asyncio
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

import antiban_core
from app import auth


def test_ip_rate_limit_drops_empty_keys():
    import time

    import main as m
    from main import RATE_WINDOW, RateLimitMiddleware

    m._rate_counters.clear()
    ip = "203.0.113.55"
    mw = RateLimitMiddleware(app=MagicMock())
    stale = time.monotonic() - RATE_WINDOW - 1

    async def run():
        req = MagicMock()
        req.url.path = "/api/status"
        req.client = MagicMock()
        req.client.host = ip
        m._rate_counters[ip] = [stale]
        await mw.dispatch(req, AsyncMock(return_value="ok"))
        assert ip in m._rate_counters
        assert len(m._rate_counters[ip]) == 1
        assert m._rate_counters[ip][0] > stale

    asyncio.run(run())


def test_normalize_proxy_field():
    assert antiban_core.normalize_proxy_field("") == ""
    assert antiban_core.normalize_proxy_field("  ") == ""
    with pytest.raises(ValueError, match="proxy"):
        antiban_core.normalize_proxy_field("bad-value")


def test_proxy_in_rejects_invalid():
    from app.routes_admin import ProxyIn

    ProxyIn(proxy="")
    with pytest.raises(ValidationError):
        ProxyIn(proxy="bad-value")
    with pytest.raises(ValidationError):
        ProxyIn(proxy="socks5://proxy.example:99999")


class _SocketStub:
    def __init__(self, response: bytes):
        self.response = bytearray(response)
        self.sent: list[bytes] = []
        self.closed = False

    def settimeout(self, _timeout):
        pass

    def sendall(self, data: bytes):
        self.sent.append(data)

    def recv(self, size: int) -> bytes:
        data = bytes(self.response[:size])
        del self.response[:size]
        return data

    def close(self):
        self.closed = True


def test_socks5_check_opens_target_tunnel(monkeypatch):
    reply = b"\x05\x00" + b"\x05\x00\x00\x01\x7f\x00\x00\x01\x01\xbb"
    sock = _SocketStub(reply)
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: sock)

    ok, error = antiban_core.check_proxy("socks5://proxy.example:1080")

    assert (ok, error) == (True, "")
    assert any(b"api.oneme.ru" in request for request in sock.sent)
    assert sock.sent[-1].endswith(b"\x01\xbb")


def test_https_proxy_wraps_tls_before_connect(monkeypatch):
    raw = _SocketStub(b"")
    tunnel = _SocketStub(b"HTTP/1.1 200 Connection established\r\n\r\n")
    wrapped = []

    class Context:
        def wrap_socket(self, sock, *, server_hostname):
            wrapped.append((sock, server_hostname))
            return tunnel

    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: raw)
    monkeypatch.setattr(antiban_core.ssl, "create_default_context", lambda: Context(), raising=False)

    ok, error = antiban_core.check_proxy("https://proxy.example:8443")

    assert (ok, error) == (True, "")
    assert wrapped == [(raw, "proxy.example")]
    assert b"CONNECT api.oneme.ru:443" in tunnel.sent[0]


def test_proxy_error_redacts_credentials(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("cannot connect user secret")

    monkeypatch.setattr(socket, "create_connection", fail)
    ok, error = antiban_core.check_proxy("socks5://user:secret@proxy.example:1080")
    assert ok is False
    assert "user" not in error
    assert "secret" not in error


def test_cached_validate_uses_cache():
    auth.clear_session_cache()
    payload = {"jti": "j1", "sub": "1", "tenant_id": 1, "tv": 0}
    with patch("app.auth.validate_token_session", return_value=None) as validate:
        assert auth.cached_validate_token_session(payload) is None
        assert auth.cached_validate_token_session(payload) is None
        validate.assert_called_once()


def test_invalidate_session_cache_forces_revalidate():
    auth.clear_session_cache()
    payload = {"jti": "j2", "sub": "1"}
    with patch("app.auth.validate_token_session", return_value=None) as validate:
        auth.cached_validate_token_session(payload)
        auth.invalidate_session_cache("j2")
        auth.cached_validate_token_session(payload)
        assert validate.call_count == 2


def test_clear_session_cache():
    auth.clear_session_cache()
    payload = {"jti": "j3", "sub": "1"}
    with patch("app.auth.validate_token_session", return_value=None) as validate:
        auth.cached_validate_token_session(payload)
        auth.clear_session_cache()
        auth.cached_validate_token_session(payload)
        assert validate.call_count == 2
