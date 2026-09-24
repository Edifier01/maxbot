import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import main as m
from app.platform_policy import AuthorizationRecord, MaxAction, MaxTransport
from app.services.max_gateway import GuardedMaxGateway


class ResolveOnlyGateway:
    def __init__(self) -> None:
        self.actions: list[str] = []

    async def resolve_destination(self, link: str):
        self.actions.append("resolve_destination")
        return None


def test_campaign_paths_do_not_call_presence_helpers() -> None:
    send_source = Path("app/campaign_send.py").read_text(encoding="utf-8-sig")
    worker_source = Path("app/campaign_worker.py").read_text(encoding="utf-8-sig")
    assert "_human_presence_before_send(" not in send_source
    assert "_maybe_idle_presence(" not in worker_source


def test_missing_destination_does_not_join() -> None:
    async def run() -> None:
        gateway = ResolveOnlyGateway()
        group = {"max_chat_id": "", "invite_link": "https://max.ru/join/fixture"}
        with pytest.raises(m.DestinationAuthorizationError) as caught:
            await m.resolve_chat_id(gateway, group)
        assert caught.value.code == "MEMBERSHIP_REVIEW_REQUIRED"
        assert gateway.actions == ["resolve_destination"]

    asyncio.run(run())


def test_send_gateway_has_no_presence_side_effects() -> None:
    now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

    class SendOnlyAdapter:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def send_message(self, *, chat_id: int, text: str):
            self.calls.append(f"send:{chat_id}:{text}")
            return SimpleNamespace(id="provider-17")

        async def fetch_history(self, **_kwargs):
            raise AssertionError("history must not be called")

        async def read_message(self, *_args, **_kwargs):
            raise AssertionError("read must not be called")

        async def add_reaction(self, *_args, **_kwargs):
            raise AssertionError("reaction must not be called")

    adapter = SendOnlyAdapter()
    gateway = GuardedMaxGateway(
        adapter=adapter,
        record=AuthorizationRecord(
            schema_version=1,
            reference="fixture",
            transport=MaxTransport.AUTHORIZED_USER_SESSION,
            allowed_actions=frozenset({MaxAction.SEND}),
            valid_from=now - timedelta(minutes=1),
            valid_until=now + timedelta(minutes=1),
        ),
        clock=lambda: now,
    )

    ack = asyncio.run(gateway.send_message(chat_id=7, text="fixture"))
    assert ack.message_id == "provider-17"
    assert adapter.calls == ["send:7:fixture"]
