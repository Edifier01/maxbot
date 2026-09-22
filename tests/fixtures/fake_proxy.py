"""Loopback-only proxy fixture metadata; it never opens a socket."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeProxyPeer:
    host: str
    port: int
    requests: list[dict[str, object]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("fake proxy must be loopback-only")
