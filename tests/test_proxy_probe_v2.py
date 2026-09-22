"""T05: bounded proxy parsing and staged probing against fake sockets."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_proxy_parser_rejects_ambiguous_scheme_and_missing_port() -> None:
    from app.services.proxy_probe import ProxyParseError, parse_proxy_url

    with pytest.raises(ProxyParseError) as unsupported:
        parse_proxy_url("socksINVALID://proxy.example:1080")
    assert unsupported.value.code == "PROXY_UNSUPPORTED_SCHEME"

    with pytest.raises(ProxyParseError) as missing:
        parse_proxy_url("http://proxy.example")
    assert missing.value.code == "PROXY_URL_INVALID"


def test_proxy_parser_decodes_credentials_and_ipv6_without_reinterpreting_scheme() -> None:
    from app.services.proxy_probe import parse_proxy_url

    parsed = parse_proxy_url("socks5://user%2Bone:pass%2Ftwo@[::1]:1080")
    assert parsed.scheme == "socks5"
    assert parsed.host == "::1"
    assert parsed.port == 1080
    assert parsed.username == "user+one"
    assert parsed.password == "pass/two"


def test_fragmented_http_connect_is_read_to_terminator(monkeypatch) -> None:
    from app.services.proxy_probe import TargetConfig, TrustConfig, parse_proxy_url, probe_route

    class Socket:
        def __init__(self) -> None:
            self.parts = [b"HTTP/1.1 2", b"00 Connection established\r\n", b"X-Test: ok\r\n\r\n"]
            self.sent: list[bytes] = []

        def settimeout(self, _value):
            pass

        def sendall(self, data: bytes) -> None:
            self.sent.append(data)

        def recv(self, _size: int) -> bytes:
            return self.parts.pop(0) if self.parts else b""

        def close(self) -> None:
            pass

    sock = Socket()
    monkeypatch.setattr("socket.create_connection", lambda *_args, **_kwargs: sock)
    route = parse_proxy_url("http://proxy.example:8080")
    result = probe_route(
        route,
        TargetConfig(host="fixture.max.invalid", port=443),
        TrustConfig(tls_verify=True),
        deadline=1.0,
    )

    assert result.ok is True
    assert result.stages["proxy_connect"] == "PASS"
    assert result.stages["max_handshake"] == "NOT_CHECKED"
    assert result.otp_calls == 0
    assert b"CONNECT fixture.max.invalid:443" in sock.sent[0]


def test_proxy_probe_reports_407_eof_and_oversized_headers(monkeypatch) -> None:
    from app.services.proxy_probe import TargetConfig, TrustConfig, parse_proxy_url, probe_route

    class Socket:
        def __init__(self, response: bytes) -> None:
            self.response = response

        def settimeout(self, _value):
            pass

        def sendall(self, _data: bytes) -> None:
            pass

        def recv(self, size: int) -> bytes:
            chunk, self.response = self.response[:size], self.response[size:]
            return chunk

        def close(self) -> None:
            pass

    for response, code in (
        (b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n", "PROXY_AUTH_FAILED"),
        (b"HTTP/1.1 200", "PROXY_RESPONSE_INVALID"),
        (b"HTTP/1.1 200 " + b"x" * 16384, "PROXY_RESPONSE_INVALID"),
    ):
        monkeypatch.setattr(
            "socket.create_connection",
            lambda *_args, response=response, **_kwargs: Socket(response),
        )
        result = probe_route(
            parse_proxy_url("http://proxy.example:8080"),
            TargetConfig(host="fixture.max.invalid", port=443),
            TrustConfig(tls_verify=True),
            deadline=1.0,
        )
        assert result.ok is False
        assert result.error_code == code
        assert result.otp_calls == 0
