import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.platform_policy import AuthorizationRecord, MaxAction, MaxTransport

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


class FakeAdapter:
    def __init__(self, send_result=None) -> None:
        self.calls: list[tuple[str, object]] = []
        self.send_result = send_result or SimpleNamespace(id="provider-17", chat_id=7)

    async def send_message(self, *, chat_id: int, text: str):
        self.calls.append(("send", {"chat_id": chat_id, "text": text}))
        return self.send_result


def record(*, expires_delta: timedelta) -> AuthorizationRecord:
    return AuthorizationRecord(
        schema_version=1,
        reference="MAX-COMPANY-PERMISSION-2026-001",
        transport=MaxTransport.AUTHORIZED_USER_SESSION,
        allowed_actions=frozenset({MaxAction.SEND}),
        valid_from=NOW - timedelta(hours=1),
        valid_until=NOW + expires_delta,
    )


def test_send_is_blocked_before_adapter_call() -> None:
    from app.platform_policy import PlatformAuthorizationHold
    from app.services.max_gateway import GuardedMaxGateway

    async def run() -> None:
        adapter = FakeAdapter()
        gateway = GuardedMaxGateway(
            adapter=adapter,
            record=record(expires_delta=timedelta(seconds=-1)),
            clock=lambda: NOW,
        )

        with pytest.raises(PlatformAuthorizationHold):
            await gateway.send_message(chat_id=7, text="fixture")

        assert adapter.calls == []

    asyncio.run(run())


def test_send_requires_provider_message_id() -> None:
    from app.services.max_gateway import GuardedMaxGateway, ProviderContractError

    async def run() -> None:
        adapter = FakeAdapter(send_result=SimpleNamespace(id=None, chat_id=7))
        gateway = GuardedMaxGateway(
            adapter=adapter,
            record=record(expires_delta=timedelta(days=1)),
            clock=lambda: NOW,
        )

        with pytest.raises(ProviderContractError, match="missing_message_id"):
            await gateway.send_message(chat_id=7, text="fixture")

    asyncio.run(run())


def test_each_action_has_its_own_permission() -> None:
    from app.platform_policy import PlatformAuthorizationHold
    from app.services.max_gateway import GuardedMaxGateway

    class Adapter:
        async def resolve_group_by_link(self, _link: str):
            raise AssertionError("adapter must not be called")

    async def run() -> None:
        gateway = GuardedMaxGateway(
            adapter=Adapter(),
            record=record(expires_delta=timedelta(days=1)),
            clock=lambda: NOW,
        )
        with pytest.raises(PlatformAuthorizationHold, match="action_not_allowed"):
            await gateway.resolve_destination("https://max.example/invite")

    asyncio.run(run())


def test_live_transport_requires_stable_identity_and_ack() -> None:
    from app.platform_policy import PlatformAuthorizationHold
    from app.services.max_gateway import (
        TransportCapabilities,
        assert_live_transport_ready,
    )

    with pytest.raises(PlatformAuthorizationHold, match="unstable_client_identity"):
        assert_live_transport_ready(
            TransportCapabilities(
                name="fixture",
                official=False,
                stable_identity=False,
                provider_ack_id=True,
            ),
            record(expires_delta=timedelta(days=1)),
        )
