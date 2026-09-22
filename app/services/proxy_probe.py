"""Bounded, staged proxy probes with no MAX authentication side effects."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import re
import socket
import ssl
import time
from typing import Any
from urllib.parse import unquote, urlsplit


MAX_HEADER_BYTES = 16 * 1024
_STATUS_RE = re.compile(rb"^HTTP/1\.[01] ([1-5][0-9]{2})(?:[ \t].*)?$")
_ALLOWED_SCHEMES = frozenset({"socks5", "http", "https"})


class ProxyParseError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    def __repr__(self) -> str:
        auth = "@" if self.username is not None else ""
        return f"ProxyConfig(scheme={self.scheme!r}, host={self.host!r}, port={self.port!r}, auth={auth!r})"


@dataclass(frozen=True, slots=True)
class TargetConfig:
    host: str
    port: int


@dataclass(frozen=True, slots=True)
class TrustConfig:
    tls_verify: bool = True


@dataclass(frozen=True, slots=True)
class ProbeResult:
    ok: bool
    stages: dict[str, str]
    error_code: str | None
    checked_at: datetime
    valid_for_route_version: int | None
    max_handshake: str
    otp_calls: int


def parse_proxy_url(raw: str) -> ProxyConfig:
    """Parse one explicit supported URL; never infer a missing scheme/port."""
    value = str(raw or "").strip()
    if not value or any(ch.isspace() for ch in value):
        raise ProxyParseError("PROXY_URL_INVALID")
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError as exc:
        raise ProxyParseError("PROXY_URL_INVALID") from exc
    if scheme not in _ALLOWED_SCHEMES:
        raise ProxyParseError("PROXY_UNSUPPORTED_SCHEME")
    if not host or port is None or not 1 <= int(port) <= 65535:
        raise ProxyParseError("PROXY_URL_INVALID")
    if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ProxyParseError("PROXY_URL_INVALID")
    username = unquote(parsed.username) if parsed.username is not None else None
    password = unquote(parsed.password) if parsed.password is not None else None
    if (username is None) != (password is None) or (
        username is not None and (not username or not password)
    ):
        raise ProxyParseError("PROXY_AUTH_FAILED")
    return ProxyConfig(
        scheme=scheme,
        host=host,
        port=int(port),
        username=username,
        password=password,
    )


def _target_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _remaining(deadline: float) -> float:
    # Public API accepts a relative deadline in seconds; keep each read bounded.
    return max(0.01, float(deadline) - time.monotonic())


def _read_http_headers(sock: Any, deadline: float) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        if len(data) >= MAX_HEADER_BYTES:
            raise ProxyParseError("PROXY_RESPONSE_INVALID")
        sock.settimeout(_remaining(deadline))
        chunk = sock.recv(min(4096, MAX_HEADER_BYTES - len(data)))
        if not chunk:
            raise ProxyParseError("PROXY_RESPONSE_INVALID")
        data.extend(chunk)
    return bytes(data)


def _http_connect(sock: Any, route: ProxyConfig, target: TargetConfig, deadline: float) -> None:
    host = _target_host(target.host)
    auth = ""
    if route.username is not None and route.password is not None:
        token = base64.b64encode(f"{route.username}:{route.password}".encode()).decode("ascii")
        auth = f"Proxy-Authorization: Basic {token}\r\n"
    request = (
        f"CONNECT {host}:{int(target.port)} HTTP/1.1\r\n"
        f"Host: {host}:{int(target.port)}\r\n"
        f"{auth}\r\n"
    ).encode("ascii")
    sock.settimeout(_remaining(deadline))
    sock.sendall(request)
    response = _read_http_headers(sock, deadline)
    status_line = response.split(b"\r\n", 1)[0]
    match = _STATUS_RE.fullmatch(status_line)
    if not match:
        raise ProxyParseError("PROXY_RESPONSE_INVALID")
    status = int(match.group(1))
    if status == 407:
        raise ProxyParseError("PROXY_AUTH_FAILED")
    if status != 200:
        raise ProxyParseError("PROXY_RESPONSE_INVALID")


def _socks5_connect(sock: Any, route: ProxyConfig, target: TargetConfig, deadline: float) -> None:
    methods = b"\x02\x00" if route.username is not None else b"\x00"
    sock.settimeout(_remaining(deadline))
    sock.sendall(b"\x05" + bytes([len(methods)]) + methods)
    response = sock.recv(2)
    if len(response) != 2 or response[0] != 5 or response[1] == 255:
        raise ProxyParseError("PROXY_AUTH_FAILED" if route.username else "PROXY_RESPONSE_INVALID")
    if response[1] == 2:
        if route.username is None or route.password is None:
            raise ProxyParseError("PROXY_AUTH_FAILED")
        username = route.username.encode()
        password = route.password.encode()
        if len(username) > 255 or len(password) > 255:
            raise ProxyParseError("PROXY_AUTH_FAILED")
        sock.sendall(b"\x01" + bytes([len(username)]) + username + bytes([len(password)]) + password)
        auth = sock.recv(2)
        if len(auth) != 2 or auth[1] != 0:
            raise ProxyParseError("PROXY_AUTH_FAILED")
    elif response[1] != 0:
        raise ProxyParseError("PROXY_AUTH_FAILED")
    encoded_host = target.host.encode("idna")
    if len(encoded_host) > 255:
        raise ProxyParseError("PROXY_URL_INVALID")
    request = b"\x05\x01\x00\x03" + bytes([len(encoded_host)]) + encoded_host + int(target.port).to_bytes(2, "big")
    sock.sendall(request)
    reply = sock.recv(4)
    if len(reply) != 4 or reply[0] != 5 or reply[1] != 0:
        raise ProxyParseError("PROXY_CONNECT_FAILED")
    if reply[3] == 1:
        tail = 4
    elif reply[3] == 3:
        length = sock.recv(1)
        tail = int(length[0]) if len(length) == 1 else 0
    elif reply[3] == 4:
        tail = 16
    else:
        raise ProxyParseError("PROXY_RESPONSE_INVALID")
    if tail <= 0 or len(sock.recv(tail + 2)) != tail + 2:
        raise ProxyParseError("PROXY_RESPONSE_INVALID")


def _result(
    *,
    ok: bool,
    stages: dict[str, str],
    error_code: str | None,
    route: Any,
    max_handshake: str = "NOT_CHECKED",
) -> ProbeResult:
    return ProbeResult(
        ok=ok,
        stages=stages,
        error_code=error_code,
        checked_at=datetime.now(UTC),
        valid_for_route_version=getattr(route, "version", None),
        max_handshake=max_handshake,
        otp_calls=0,
    )


def probe_route(
    route: ProxyConfig,
    target: TargetConfig,
    trust_config: TrustConfig,
    deadline: float,
) -> ProbeResult:
    """Probe TCP/proxy (and optional proxy TLS) only; never requests an OTP."""
    if not trust_config.tls_verify:
        return _result(
            ok=False,
            stages={"proxy_tcp": "NOT_RUN", "proxy_connect": "NOT_RUN", "max_handshake": "NOT_CHECKED"},
            error_code="TLS_ERROR",
            route=route,
        )
    stages = {"proxy_tcp": "NOT_RUN", "proxy_connect": "NOT_RUN", "tls": "NOT_CHECKED", "max_handshake": "NOT_CHECKED"}
    absolute_deadline = time.monotonic() + max(0.01, float(deadline))
    sock: Any = None
    try:
        sock = socket.create_connection((route.host, route.port), timeout=_remaining(absolute_deadline))
        stages["proxy_tcp"] = "PASS"
        if route.scheme == "https":
            context = ssl.create_default_context()
            sock = context.wrap_socket(sock, server_hostname=route.host)
            stages["tls"] = "PASS"
        if route.scheme in {"http", "https"}:
            _http_connect(sock, route, target, absolute_deadline)
        else:
            _socks5_connect(sock, route, target, absolute_deadline)
        stages["proxy_connect"] = "PASS"
        return _result(ok=True, stages=stages, error_code=None, route=route)
    except ProxyParseError as exc:
        stages["proxy_connect"] = "FAIL"
        return _result(ok=False, stages=stages, error_code=exc.code, route=route)
    except (OSError, ssl.SSLError, TimeoutError):
        stages["proxy_connect"] = "FAIL"
        return _result(ok=False, stages=stages, error_code="PROXY_CONNECT_FAILED", route=route)
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
