import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

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


def test_authorized_reaction_forwards_sdk_identifiers_and_unicode_reaction() -> None:
    from app.services.max_gateway import GuardedMaxGateway

    calls: list[tuple[int, int, str]] = []
    result = object()

    class ReactionAdapter:
        async def add_reaction(
            self, chat_id: int, message_id: int, reaction: str
        ):
            calls.append((chat_id, message_id, reaction))
            return result

    now = NOW
    authorization = AuthorizationRecord(
        schema_version=1,
        reference="fixture-reaction",
        transport=MaxTransport.AUTHORIZED_USER_SESSION,
        allowed_actions=frozenset({MaxAction.ADD_REACTION}),
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=1),
    )
    gateway = GuardedMaxGateway(
        adapter=ReactionAdapter(), record=authorization, clock=lambda: now
    )

    actual = asyncio.run(
        gateway.add_reaction(chat_id=73, message_id=901, reaction="👍")
    )

    assert actual is result
    assert calls == [(73, 901, "👍")]


def test_reaction_without_explicit_action_permission_never_reaches_adapter() -> None:
    from app.platform_policy import PlatformAuthorizationHold
    from app.services.max_gateway import GuardedMaxGateway

    class ReactionAdapter:
        def add_reaction(self, *_args, **_kwargs):
            raise AssertionError("adapter must not be called")

    now = NOW
    authorization = AuthorizationRecord(
        schema_version=1,
        reference="fixture-send-only",
        transport=MaxTransport.AUTHORIZED_USER_SESSION,
        allowed_actions=frozenset({MaxAction.SEND}),
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=1),
    )
    gateway = GuardedMaxGateway(
        adapter=ReactionAdapter(), record=authorization, clock=lambda: now
    )

    with pytest.raises(PlatformAuthorizationHold, match="action_not_allowed"):
        asyncio.run(
            gateway.add_reaction(chat_id=73, message_id=901, reaction="👍")
        )


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


def test_auxiliary_restriction_handler_runs_before_error_is_rethrown() -> None:
    from app.services.max_gateway import GuardedMaxGateway

    class Adapter:
        async def fetch_history(self, *_args, **_kwargs):
            raise RuntimeError("flood wait 3600 seconds")

    calls: list[tuple[MaxAction, str]] = []

    async def record(action: MaxAction, error: BaseException) -> None:
        calls.append((action, str(error)))

    async def run() -> None:
        gateway = GuardedMaxGateway(
            adapter=Adapter(),
            record=AuthorizationRecord(
                schema_version=1,
                reference="fixture",
                transport=MaxTransport.AUTHORIZED_USER_SESSION,
                allowed_actions=frozenset({MaxAction.FETCH_HISTORY}),
                valid_from=NOW - timedelta(minutes=1),
                valid_until=NOW + timedelta(minutes=1),
            ),
            clock=lambda: NOW,
            restriction_handler=record,
        )
        with pytest.raises(RuntimeError, match="flood wait 3600 seconds"):
            await gateway.fetch_history(chat_id=7)

    asyncio.run(run())
    assert calls == [(MaxAction.FETCH_HISTORY, "flood wait 3600 seconds")]


def test_auxiliary_wait_updates_shared_cooldown(monkeypatch) -> None:
    import main as m

    persist = Mock()
    monkeypatch.setattr(m, "_persist_server_retry_after", persist)

    asyncio.run(
        m._handle_auxiliary_provider_error(
            7, MaxAction.MARK_READ, RuntimeError("flood wait 7200 seconds")
        )
    )

    persist.assert_called_once_with(7, 7200, reason="MAX auxiliary mark_read")


def test_auxiliary_ban_updates_profile_and_stops_tenant(monkeypatch) -> None:
    import main as m

    mark_failed = Mock(return_value=True)
    stop = AsyncMock()
    monkeypatch.setattr(m, "_mark_profile_failed", mark_failed)
    monkeypatch.setattr(m, "_handle_profile_banned", stop)

    asyncio.run(
        m._handle_auxiliary_provider_error(
            7, MaxAction.ADD_REACTION, RuntimeError("account banned")
        )
    )

    mark_failed.assert_called_once_with(7, "account banned", is_auth_err=False)
    stop.assert_awaited_once_with(7, "account banned")


def test_max_gateway_wires_auxiliary_restriction_handler(monkeypatch) -> None:
    import main as m
    from app.services.max_gateway import GuardedMaxGateway

    class Adapter:
        async def read_message(self, **_kwargs):
            raise RuntimeError("flood wait 120 seconds")

    handler = AsyncMock()
    now = datetime.now(UTC)
    authorization = AuthorizationRecord(
        schema_version=1,
        reference="fixture",
        transport=MaxTransport.AUTHORIZED_USER_SESSION,
        allowed_actions=frozenset({MaxAction.MARK_READ}),
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=1),
    )
    monkeypatch.setattr(m, "_platform_authorization_record", lambda: authorization)
    monkeypatch.setattr(m, "_handle_auxiliary_provider_error", handler)
    token = m._gateway_profile_id.set(7)
    try:
        gateway = m._max_gateway(Adapter())
        assert isinstance(gateway, GuardedMaxGateway)

        async def run() -> None:
            with pytest.raises(RuntimeError, match="flood wait 120 seconds"):
                await gateway.mark_read(message_id=17)

        asyncio.run(run())
    finally:
        m._gateway_profile_id.reset(token)

    handler.assert_awaited_once()
    assert handler.await_args.args[0:2] == (7, MaxAction.MARK_READ)


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


def test_session_required_send_does_not_start_otp_or_relogin() -> None:
    from app.services.max_gateway import GuardedMaxGateway

    class Adapter:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def send_message(self, *, chat_id: int, text: str):
            del chat_id, text
            self.calls.append("send_message")
            raise RuntimeError("session_required")

        async def request_otp(self):
            self.calls.append("request_otp")
            raise AssertionError("send failure must not trigger OTP")

    async def run() -> None:
        adapter = Adapter()
        gateway = GuardedMaxGateway(
            adapter=adapter,
            record=record(expires_delta=timedelta(days=1)),
            clock=lambda: NOW,
        )

        with pytest.raises(RuntimeError, match="session_required"):
            await gateway.send_message(chat_id=7, text="fixture")

        assert adapter.calls == ["send_message"]

    asyncio.run(run())
