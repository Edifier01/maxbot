"""A fake MAX adapter that records calls and cannot open a socket."""

from __future__ import annotations


class LiveNetworkBlocked(RuntimeError):
    """Raised if a test tries to use the live MAX transport."""


class FakeMaxClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.network_attempted = False

    async def connect(self) -> None:
        self.calls.append("connect")
        raise LiveNetworkBlocked("fake MAX transport has no network")

    def report(self) -> dict[str, object]:
        return {
            "calls": list(self.calls),
            "network_attempted": self.network_attempted,
        }
