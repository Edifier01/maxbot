"""Single guarded boundary for MAX adapter calls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from inspect import isawaitable
from typing import Any, Callable

from app import recovery_hold
from app.platform_policy import (
    AuthorizationRecord,
    MaxAction,
    MaxTransport,
    PlatformAuthorizationHold,
    require_action,
)


@dataclass(frozen=True, slots=True)
class TransportCapabilities:
    name: str
    official: bool
    stable_identity: bool
    provider_ack_id: bool


@dataclass(frozen=True, slots=True)
class ProviderAck:
    message_id: str
    chat_id: str
    accepted_at: datetime


class ProviderContractError(RuntimeError):
    """Raised when the provider response cannot establish acceptance."""


def assert_live_transport_ready(
    capabilities: TransportCapabilities,
    record: AuthorizationRecord,
) -> None:
    """Reject a live transport without stable identity and provider ACK support."""
    if record.transport is MaxTransport.AUTHORIZED_USER_SESSION:
        if not capabilities.stable_identity:
            raise PlatformAuthorizationHold("unstable_client_identity")
        if not capabilities.provider_ack_id:
            raise PlatformAuthorizationHold("provider_ack_unverified")


class GuardedMaxGateway:
    """Apply the action authorization check before every adapter network call."""

    def __init__(
        self,
        adapter: Any,
        record: AuthorizationRecord,
        *,
        clock: Callable[[], datetime],
        restriction_handler: Callable[[MaxAction, BaseException], Any] | None = None,
    ) -> None:
        self._adapter = adapter
        self._record = record
        self._clock = clock
        self._restriction_handler = restriction_handler

    def _require(self, action: MaxAction) -> None:
        recovery_hold.require_external_actions_released()
        require_action(
            self._record,
            action,
            MaxTransport.AUTHORIZED_USER_SESSION,
            now=self._clock(),
        )

    async def _call(self, action: MaxAction, method: str, *args: Any, **kwargs: Any) -> Any:
        self._require(action)
        try:
            result = getattr(self._adapter, method)(*args, **kwargs)
            if isawaitable(result):
                return await result
            return result
        except Exception as exc:
            if self._restriction_handler is not None:
                handled = self._restriction_handler(action, exc)
                if isawaitable(handled):
                    await handled
            raise

    async def connect(self) -> Any:
        return await self._call(MaxAction.CONNECT, "connect")

    async def request_otp(self, *args: Any, **kwargs: Any) -> Any:
        return await self._call(MaxAction.REQUEST_OTP, "request_otp", *args, **kwargs)

    async def verify_auth(self, *args: Any, **kwargs: Any) -> Any:
        return await self._call(MaxAction.VERIFY_AUTH, "verify_auth", *args, **kwargs)

    async def resolve_destination(self, link: str) -> Any:
        return await self._call(
            MaxAction.RESOLVE_DESTINATION,
            "resolve_group_by_link",
            link,
        )

    async def check_destination(self, *, chat_id: int) -> Any:
        return await self._call(MaxAction.CHECK_DESTINATION, "get_chat", chat_id)

    async def join_destination(self, link: str) -> Any:
        return await self._call(MaxAction.JOIN_DESTINATION, "join_group", link)

    async def send_message(self, *, chat_id: int, text: str) -> ProviderAck:
        result = await self._call(
            MaxAction.SEND,
            "send_message",
            chat_id=chat_id,
            text=text,
        )
        message_id = str(getattr(result, "id", "") or "").strip()
        if not message_id:
            raise ProviderContractError("missing_message_id")
        accepted_at = self._clock()
        if accepted_at.tzinfo is None or accepted_at.utcoffset() is None:
            raise ProviderContractError("accepted_at_not_aware")
        return ProviderAck(
            message_id=message_id,
            chat_id=str(chat_id),
            accepted_at=accepted_at.astimezone(UTC),
        )

    async def fetch_history(self, *args: Any, **kwargs: Any) -> Any:
        return await self._call(MaxAction.FETCH_HISTORY, "fetch_history", *args, **kwargs)

    async def mark_read(self, *args: Any, **kwargs: Any) -> Any:
        return await self._call(MaxAction.MARK_READ, "read_message", *args, **kwargs)

    async def add_reaction(self, *args: Any, **kwargs: Any) -> Any:
        return await self._call(MaxAction.ADD_REACTION, "add_reaction", *args, **kwargs)

    async def probe(self, *args: Any, **kwargs: Any) -> Any:
        return await self._call(MaxAction.PROBE, "probe", *args, **kwargs)
