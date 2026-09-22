"""T01: deterministic fixtures must never reach a real MAX or proxy."""

from __future__ import annotations

import asyncio

import pytest

from tests.fixtures.fake_max import FakeMaxClient, LiveNetworkBlocked
from tests.fixtures.fake_proxy import FakeProxyPeer


def test_fake_max_blocks_external_transport_before_network() -> None:
    client = FakeMaxClient()

    with pytest.raises(LiveNetworkBlocked):
        asyncio.run(client.connect())

    assert client.calls == ["connect"]
    assert client.network_attempted is False


def test_fake_proxy_is_loopback_only() -> None:
    peer = FakeProxyPeer(host="127.0.0.1", port=0)
    assert peer.host == "127.0.0.1"
    assert peer.port == 0
    assert peer.requests == []


def test_identical_fixture_reports_are_comparable() -> None:
    first = FakeMaxClient().report()
    second = FakeMaxClient().report()
    assert first == second
    assert first == {"calls": [], "network_attempted": False}
