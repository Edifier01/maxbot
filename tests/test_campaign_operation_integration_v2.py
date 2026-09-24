"""T12 integration: the legacy send path must use one durable operation."""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _setup_local_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("MAX_SERVER_MODE", "0")
    monkeypatch.setenv("MAX_DATA", str(tmp_path / "data"))
    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.reset_test_runtime()
    m.init_db()
    with m._conn() as connection:
        connection.execute(
            "INSERT INTO profiles (id, phone, status) VALUES (7, '+79990007777', 'active')"
        )
        connection.execute(
            "INSERT INTO groups (id, name, max_chat_id, destination_verified, is_active) "
            "VALUES (3, 'fixture', '77', 1, 1)"
        )
        connection.execute(
            "INSERT INTO group_profiles (group_id, profile_id, is_enabled) VALUES (3, 7, 1)"
        )
        profile = connection.execute("SELECT * FROM profiles WHERE id=7").fetchone()
        group = connection.execute("SELECT * FROM groups WHERE id=3").fetchone()
    return m, profile, group


class _FakeGateway:
    def __init__(self, *, send_error: BaseException | None = None) -> None:
        self.send_error = send_error
        self.check_calls = 0
        self.send_calls = 0

    async def check_destination(self, *, chat_id: int) -> None:
        self.check_calls += 1

    async def send_message(self, *, chat_id: int, text: str):
        self.send_calls += 1
        if self.send_error is not None:
            raise self.send_error
        return SimpleNamespace(message_id="provider-77")


class _MembershipReviewGateway(_FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.resolve_calls = 0

    async def resolve_destination(self, _link: str):
        self.resolve_calls += 1
        return None


def _install_common_send_fakes(m, monkeypatch, gateway, *, max_retry: int = 1):
    monkeypatch.setattr(m, "MAX_RETRY", max_retry)
    monkeypatch.setattr(m, "RETRY_DELAYS", [0] * max_retry)
    monkeypatch.setattr(m, "_prepare_outgoing_text", lambda text, *_a, **_k: text)
    monkeypatch.setattr(m, "_max_gateway", lambda _client: gateway)
    monkeypatch.setattr(m, "_touch_worker_activity", lambda: None)
    monkeypatch.setattr(m, "_on_success", lambda _profile_id: None)
    monkeypatch.setattr(m, "_note_human_burst", lambda _profile_id: None)
    monkeypatch.setattr(m, "_metric_inc", lambda _key: None)
    monkeypatch.setattr(m, "append_log", lambda _message: None)

    async def with_fake_client(_profile_id, _phone, callback, **_kwargs):
        return await callback(object())

    monkeypatch.setattr(m, "_with_client", with_fake_client)


def test_legacy_send_persists_one_accepted_operation_and_provider_id(
    tmp_path, monkeypatch
) -> None:
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import send_with_retry

    gateway = _FakeGateway()
    _install_common_send_fakes(m, monkeypatch, gateway)

    result = asyncio.run(send_with_retry(profile, group, "fixture text", 0, 0, 0, 0))

    assert result is True
    with m._conn() as connection:
        operation = connection.execute(
            "SELECT operation_id, status, provider_message_id FROM operations"
        ).fetchone()
        send_log = connection.execute(
            "SELECT operation_id, status FROM send_log"
        ).fetchone()
    assert dict(operation) == {
        "operation_id": send_log["operation_id"],
        "status": "accepted",
        "provider_message_id": "provider-77",
    }
    assert send_log["status"] == "sent"
    assert gateway.send_calls == 1


def test_client_return_without_send_is_not_accepted_or_unknown(
    tmp_path, monkeypatch
) -> None:
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import send_with_retry

    gateway = _FakeGateway()
    _install_common_send_fakes(m, monkeypatch, gateway)

    async def without_callback(_profile_id, _phone, _callback, **_kwargs):
        return None

    monkeypatch.setattr(m, "_with_client", without_callback)

    result = asyncio.run(send_with_retry(profile, group, "fixture text", 0, 0, 0, 0))

    assert result is False
    assert gateway.send_calls == 0
    with m._conn() as connection:
        operation = connection.execute(
            "SELECT status FROM operations"
        ).fetchone()
        send_log = connection.execute(
            "SELECT status FROM send_log"
        ).fetchone()
    assert operation["status"] == "failed_unsent"
    assert send_log["status"] == "failed"


def test_unknown_send_persists_only_safe_error_metadata(
    tmp_path, monkeypatch
) -> None:
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import send_with_retry

    secret = "proxy_password=fixture-private-value"
    gateway = _FakeGateway(send_error=TimeoutError(f"response lost; {secret}"))
    log_messages: list[str] = []
    _install_common_send_fakes(m, monkeypatch, gateway)
    monkeypatch.setattr(m, "append_log", log_messages.append)

    assert asyncio.run(
        send_with_retry(profile, group, "fixture text", 0, 0, 0, 0)
    ) is False

    with m._conn() as connection:
        operation = connection.execute(
            "SELECT status, last_error FROM operations"
        ).fetchone()
        send_log = connection.execute(
            "SELECT status, error FROM send_log"
        ).fetchone()

    assert operation["status"] == "unknown"
    assert send_log["status"] == "unknown"
    assert "неизвестен" in operation["last_error"].lower()
    assert operation["last_error"] == send_log["error"]
    assert all(
        secret not in value
        for value in (operation["last_error"], send_log["error"], *log_messages)
    )
    assert any("неизвестен" in message.lower() for message in log_messages)
    assert gateway.send_calls == 1


def test_rejected_send_persists_only_safe_error_metadata(
    tmp_path, monkeypatch
) -> None:
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import send_with_retry

    secret = "proxy_password=fixture-private-value"
    log_messages: list[str] = []
    gateway = _FakeGateway()
    _install_common_send_fakes(m, monkeypatch, gateway, max_retry=2)
    monkeypatch.setattr(m, "append_log", log_messages.append)
    client_attempts = 0

    async def fail_before_gateway(*_args, **_kwargs):
        nonlocal client_attempts
        client_attempts += 1
        raise RuntimeError(f"connection rejected; {secret}")

    monkeypatch.setattr(m, "_with_client", fail_before_gateway)

    assert asyncio.run(
        send_with_retry(profile, group, "fixture text", 0, 0, 0, 0)
    ) is False

    with m._conn() as connection:
        operation = connection.execute(
            "SELECT status, last_error FROM operations"
        ).fetchone()
        send_log = connection.execute(
            "SELECT status, error FROM send_log"
        ).fetchone()
        failed_profile = connection.execute(
            "SELECT status, last_error FROM profiles WHERE id=?", (profile["id"],)
        ).fetchone()

    assert operation["status"] == "failed_unsent"
    assert send_log["status"] == "failed"
    assert failed_profile["status"] == m.ProfileStatus.ACTIVE
    assert operation["last_error"]
    assert operation["last_error"] == send_log["error"]
    assert all(
        secret not in value
        for value in (
            operation["last_error"],
            send_log["error"],
            failed_profile["last_error"],
            *log_messages,
        )
    )
    assert client_attempts == 2
    assert any("повтор через" in message for message in log_messages)
    assert gateway.send_calls == 0


def test_membership_review_stops_before_send_without_retrying(
    tmp_path, monkeypatch
) -> None:
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import send_with_retry

    with m._conn() as connection:
        connection.execute(
            "UPDATE groups SET max_chat_id='', invite_link=? WHERE id=?",
            ("https://max.example/review", int(group["id"])),
        )
        group = connection.execute(
            "SELECT * FROM groups WHERE id=?", (int(group["id"]),)
        ).fetchone()

    gateway = _MembershipReviewGateway()
    _install_common_send_fakes(m, monkeypatch, gateway, max_retry=3)

    assert asyncio.run(send_with_retry(profile, group, "fixture text", 0, 0, 0, 0)) is False
    assert gateway.resolve_calls == 0
    assert gateway.send_calls == 0
    with m._conn() as connection:
        operation = connection.execute(
            "SELECT status, last_error FROM operations"
        ).fetchone()
        send_log = connection.execute(
            "SELECT status, error FROM send_log"
        ).fetchone()
    assert tuple(operation) == ("failed_unsent", "DESTINATION_REVIEW_REQUIRED")
    assert tuple(send_log) == ("failed", "DESTINATION_REVIEW_REQUIRED")


def test_destination_change_blocks_queued_send_until_explicit_confirmation(
    tmp_path, monkeypatch
) -> None:
    """T11/AUD20-A18: old history stays pinned; new work needs confirmation."""
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.repositories.automation_scope import AutomationScopeRepository
    from app.campaign_send import send_with_retry

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=5, daily_limit_day=?, "
            "sent_day=?, messages_sent_today=0 WHERE id=?",
            (today, today, int(profile["id"])),
        )
        profile = connection.execute(
            "SELECT * FROM profiles WHERE id=?", (int(profile["id"]),)
        ).fetchone()
        group = connection.execute(
            "SELECT * FROM groups WHERE id=?", (int(group["id"]),)
        ).fetchone()

    gateway = _FakeGateway()
    _install_common_send_fakes(m, monkeypatch, gateway)

    assert asyncio.run(send_with_retry(profile, group, "old route", 0, 0, 0, 0)) is True
    with m._conn() as connection:
        old_group = connection.execute(
            "SELECT * FROM groups WHERE id=?", (int(group["id"]),)
        ).fetchone()
        old_operation = connection.execute(
            "SELECT status, route_snapshot_json FROM operations "
            "ORDER BY rowid LIMIT 1"
        ).fetchone()
    assert old_group["destination_revision"] == 0
    assert '"chat_id": "77"' in old_operation["route_snapshot_json"]

    with m._conn() as connection:
        AutomationScopeRepository(connection).update_destination(
            int(group["id"]), "https://max.example/new"
        )
        changed_group = connection.execute(
            "SELECT * FROM groups WHERE id=?", (int(group["id"]),)
        ).fetchone()

    assert asyncio.run(
        send_with_retry(profile, changed_group, "must wait", 1, 0, 0, 0)
    ) is False
    assert gateway.send_calls == 1
    with m._conn() as connection:
        blocked = connection.execute(
            "SELECT status, last_error FROM operations "
            "WHERE status='failed_unsent'"
        ).fetchone()
    assert tuple(blocked) == ("failed_unsent", "DESTINATION_REVIEW_REQUIRED")

    with m._conn() as connection:
        repository = AutomationScopeRepository(connection)
        repository.verify_destination(int(group["id"]), "88")
        confirmed_group = connection.execute(
            "SELECT * FROM groups WHERE id=?", (int(group["id"]),)
        ).fetchone()

    assert asyncio.run(
        send_with_retry(profile, old_group, "stale route", 2, 0, 0, 0)
    ) is False
    assert gateway.send_calls == 1

    assert asyncio.run(
        send_with_retry(profile, confirmed_group, "new route", 3, 0, 0, 0)
    ) is True
    assert gateway.send_calls == 2
    with m._conn() as connection:
        routes = [
            row["route_snapshot_json"]
            for row in connection.execute(
                "SELECT route_snapshot_json FROM operations "
                "WHERE status='accepted' ORDER BY rowid"
            ).fetchall()
        ]
    assert len(routes) == 2
    assert '"chat_id": "77"' in routes[0]
    assert '"chat_id": "88"' in routes[1]


def test_auxiliary_wait_persists_deadline_and_fences_next_selection(
    tmp_path, monkeypatch
) -> None:
    """T13-C07/COMP-R05: auxiliary wait blocks the next local claim."""
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.platform_policy import MaxAction

    asyncio.run(
        m._handle_auxiliary_provider_error(
            int(profile["id"]),
            MaxAction.MARK_READ,
            RuntimeError("flood wait 7200 seconds"),
        )
    )

    with m._conn() as connection:
        current_profile = connection.execute(
            "SELECT * FROM profiles WHERE id=?", (int(profile["id"]),)
        ).fetchone()
    assert current_profile["cooldown_until"]
    assert m._can_send_in_group(current_profile, int(group["id"])) is False


def test_auxiliary_wait_prevents_worker_claiming_the_following_send(
    tmp_path, monkeypatch
) -> None:
    """T13-C07/COMP-R05: the persisted auxiliary sanction gates the real claim path."""
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_worker import _claim_next_job_sync
    from app.platform_policy import (
        AuthorizationRecord,
        MaxAction,
        MaxTransport,
    )

    m.set_setting("campaign_goal", "message_pool")
    m.set_setting("message_pick_mode", "sequential")
    m.set_setting("role_plan_enabled", "0")
    monkeypatch.setattr(m, "load_message_pool", lambda: ["fixture text"])
    from app.routes_campaign import CampaignCommandCoordinator

    with m._conn() as connection:
        CampaignCommandCoordinator(connection, scope="local")
        connection.execute("UPDATE queue_state SET running=1 WHERE id=1")
        connection.execute(
            "UPDATE campaign_control SET auto_run=1, stop_requested=0, state='running' "
            "WHERE scope='local'"
        )

    assert m._can_send_in_group(profile, int(group["id"])) is True
    now = datetime.now(timezone.utc)
    authorization = AuthorizationRecord(
        schema_version=1,
        reference="fixture-only",
        transport=MaxTransport.AUTHORIZED_USER_SESSION,
        allowed_actions=frozenset({MaxAction.MARK_READ}),
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=1),
    )
    monkeypatch.setattr(m, "_platform_authorization_record", lambda: authorization)

    class AuxiliaryAdapter:
        def __init__(self) -> None:
            self.send_calls = 0

        async def read_message(self, *, message_id: int) -> None:
            assert message_id == 17
            raise RuntimeError("flood wait 7200 seconds")

        async def send_message(self, *, chat_id: int, text: str):
            self.send_calls += 1
            return SimpleNamespace(id="unexpected-provider-ack")

    adapter = AuxiliaryAdapter()
    profile_token = m._gateway_profile_id.set(int(profile["id"]))
    try:
        gateway = m._max_gateway(adapter)

        async def trigger_auxiliary_wait() -> None:
            with pytest.raises(RuntimeError, match="flood wait 7200 seconds"):
                await gateway.mark_read(message_id=17)

        asyncio.run(trigger_auxiliary_wait())
    finally:
        m._gateway_profile_id.reset(profile_token)

    job = _claim_next_job_sync()

    assert job is None
    assert adapter.send_calls == 0
    with m._conn() as connection:
        cooldown = connection.execute(
            "SELECT cooldown_until FROM profiles WHERE id=?", (int(profile["id"]),)
        ).fetchone()[0]
    assert cooldown


def test_auxiliary_ban_persists_stop_before_next_selection(tmp_path, monkeypatch) -> None:
    """T13-C07/COMP-R05: auxiliary ban is durable and stops the tenant."""
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.platform_policy import MaxAction

    stop = AsyncMock()
    monkeypatch.setattr(m, "_handle_profile_banned", stop)
    asyncio.run(
        m._handle_auxiliary_provider_error(
            int(profile["id"]),
            MaxAction.ADD_REACTION,
            RuntimeError("account banned"),
        )
    )

    with m._conn() as connection:
        current_profile = connection.execute(
            "SELECT status FROM profiles WHERE id=?", (int(profile["id"]),)
        ).fetchone()
    assert current_profile["status"] == m.ProfileStatus.BANNED
    assert m._active_profiles_for_group(int(group["id"])) == []
    stop.assert_awaited_once_with(int(profile["id"]), "account banned")


def test_legacy_accounting_is_idempotent_for_one_operation(
    tmp_path, monkeypatch
) -> None:
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    import app.campaign_send as campaign_send
    from app.campaign_send import send_with_retry

    gateway = _FakeGateway()
    _install_common_send_fakes(m, monkeypatch, gateway)

    assert asyncio.run(send_with_retry(profile, group, "fixture text", 0, 0, 0, 0)) is True
    with m._conn() as connection:
        operation_id = connection.execute(
            "SELECT operation_id FROM operations"
        ).fetchone()["operation_id"]

    campaign_send._persist_send_outcome(
        profile=profile,
        group=group,
        mi=0,
        pi=0,
        gi_next=0,
        mi_next=0,
        status="sent",
        sent_text="fixture text",
        advance_queue=False,
        operation_id=operation_id,
    )

    with m._conn() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM send_log WHERE operation_id=?",
            (operation_id,),
        ).fetchone()[0]
        sent_today = connection.execute(
            "SELECT messages_sent_today FROM profiles WHERE id=7"
        ).fetchone()[0]
    assert count == 1
    assert sent_today == 1


def test_ack_after_midnight_keeps_authorization_budget_date(
    tmp_path, monkeypatch
) -> None:
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import send_with_retry

    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET sent_day=?, messages_sent_today=0 WHERE id=7",
            ("2026-09-21",),
        )
    current = [date(2026, 9, 20)]
    monkeypatch.setattr(m, "_local_today", lambda: current[0])

    class MidnightGateway(_FakeGateway):
        async def send_message(self, *, chat_id: int, text: str):
            current[0] = date(2026, 9, 21)
            return await super().send_message(chat_id=chat_id, text=text)

    gateway = MidnightGateway()
    _install_common_send_fakes(m, monkeypatch, gateway)

    assert asyncio.run(send_with_retry(profile, group, "fixture text", 0, 0, 0, 0)) is True

    with m._conn() as connection:
        operation = connection.execute(
            "SELECT budget_date, status FROM operations"
        ).fetchone()
        profile_after = connection.execute(
            "SELECT sent_day, messages_sent_today FROM profiles WHERE id=7"
        ).fetchone()
    assert tuple(operation) == ("2026-09-20", "accepted")
    assert tuple(profile_after) == ("2026-09-21", 0)


def test_unknown_operation_occupies_daily_reservation_after_restart(
    tmp_path, monkeypatch
) -> None:
    m, profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from app.repositories.operations import OperationRepository
    from app.services.operations import OperationLedger

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=?, daily_limit_day=?, "
            "sent_day=?, messages_sent_today=0 WHERE id=7",
            (1, today, today),
        )
        ledger = OperationLedger(OperationRepository(connection))
        operation = ledger.create_operation(
            scope="local",
            profile_id=7,
            group_id=3,
            text="unknown fixture",
            budget_date=today,
            max_pre_effect_retries=1,
        )
        ledger.claim(operation.operation_id, profile_id=7)
        ledger.mark_in_flight(operation.operation_id)
        ledger.mark_unknown(operation.operation_id, "timeout after transmit")
        profile = connection.execute(
            "SELECT * FROM profiles WHERE id=7"
        ).fetchone()

    assert m._reserved_hits_daily_limit(profile) is True


def test_duplicate_group_records_share_one_configured_profile_cap(
    tmp_path, monkeypatch
) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    today = m._local_today().isoformat()
    with m._conn() as connection:
        # This fixture isolates the legacy cap behavior from the separate
        # explicit work-group-selection gate.
        connection.execute("DROP TABLE profile_automation_scope")
        connection.execute(
            "INSERT INTO groups "
            "(id, name, max_chat_id, invite_link, is_active) "
            "VALUES (4, 'duplicate-record', '77', 'https://max.example/fixture', 1)"
        )
        connection.execute(
            "INSERT INTO group_profiles (group_id, profile_id, is_enabled) "
            "VALUES (4, 7, 1)"
        )
        connection.execute(
            "UPDATE profiles SET daily_limit=5, daily_limit_day=?, "
            "sent_day=?, messages_sent_today=4 WHERE id=7",
            (today, today),
        )
        profile = connection.execute(
            "SELECT * FROM profiles WHERE id=7"
        ).fetchone()

    assert m._can_send_in_group(profile, 3) is True
    assert m._can_send_in_group(profile, 4) is True

    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET messages_sent_today=5 WHERE id=7"
        )
        capped = connection.execute(
            "SELECT * FROM profiles WHERE id=7"
        ).fetchone()

    assert m._can_send_in_group(capped, 3) is False
    assert m._can_send_in_group(capped, 4) is False


def test_legacy_manual_operation_reserves_only_unallocated_budget(
    tmp_path, monkeypatch
) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import send_with_retry

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=1, daily_limit_day=?, "
            "sent_day=?, messages_sent_today=0 WHERE id=7",
            (today, today),
        )

    gateway = _FakeGateway()
    _install_common_send_fakes(m, monkeypatch, gateway)
    profile = m._conn().execute("SELECT * FROM profiles WHERE id=7").fetchone()
    group = m._conn().execute("SELECT * FROM groups WHERE id=3").fetchone()

    assert asyncio.run(send_with_retry(profile, group, "first", 0, 0, 0, 0)) is True
    assert asyncio.run(send_with_retry(profile, group, "second", 0, 0, 0, 0)) is False
    assert gateway.send_calls == 1
    with m._conn() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM operations"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM send_log WHERE status='sent'"
        ).fetchone()[0] == 1


def test_concurrent_legacy_manual_operations_share_one_reservation(
    tmp_path, monkeypatch
) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import send_with_retry

    today = m._local_today().isoformat()
    with m._conn() as connection:
        connection.execute(
            "UPDATE profiles SET daily_limit=1, daily_limit_day=?, "
            "sent_day=?, messages_sent_today=0 WHERE id=7",
            (today, today),
        )

    gateway = _FakeGateway()
    _install_common_send_fakes(m, monkeypatch, gateway)
    profile = m._conn().execute("SELECT * FROM profiles WHERE id=7").fetchone()
    group = m._conn().execute("SELECT * FROM groups WHERE id=3").fetchone()
    entered_client = asyncio.Event()
    release_client = asyncio.Event()

    async def blocked_client(_profile_id, _phone, callback, **_kwargs):
        entered_client.set()
        await release_client.wait()
        return await callback(object())

    monkeypatch.setattr(m, "_with_client", blocked_client)

    async def run() -> tuple[bool, bool]:
        first = asyncio.create_task(
            send_with_retry(profile, group, "first", 0, 0, 0, 0)
        )
        await entered_client.wait()
        second = asyncio.create_task(
            send_with_retry(profile, group, "second", 0, 0, 0, 0)
        )
        second_result = await second
        release_client.set()
        first_result = await first
        return first_result, second_result

    assert asyncio.run(run()) == (True, False)
    assert gateway.send_calls == 1
    with m._conn() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM operations"
        ).fetchone()[0] == 1


def test_short_pause_respects_configured_minimum_floor(tmp_path, monkeypatch) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    import app.campaign_send as campaign_send
    from app.campaign_send import compute_send_delay_sec

    m.set_setting("delay_min_sec", "180")
    m.set_setting("delay_max_sec", "240")
    m.set_setting("human_pauses_enabled", "1")
    m.set_setting("long_pause_chance", "0")
    m.set_setting("short_pause_chance", "100")
    m.set_setting("short_pause_min_sec", "30")
    m.set_setting("short_pause_max_sec", "50")
    monkeypatch.setattr(campaign_send.random, "random", lambda: 0.0)
    monkeypatch.setattr(
        campaign_send.antiban_core,
        "lognormal_delay_sec",
        lambda lo, _hi, *, jitter_percent: lo,
    )

    delay, kind = compute_send_delay_sec()

    assert kind == "short"
    assert delay >= 180


def test_server_retry_after_is_persisted_without_shortening(
    tmp_path, monkeypatch
) -> None:
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import send_with_retry

    class RetryAfterGateway(_FakeGateway):
        async def check_destination(self, *, chat_id: int) -> None:
            self.check_calls += 1
            raise RuntimeError("flood wait 172800 seconds")

    gateway = RetryAfterGateway()
    _install_common_send_fakes(m, monkeypatch, gateway, max_retry=1)
    before = datetime.now(timezone.utc)

    result = asyncio.run(send_with_retry(profile, group, "fixture text", 0, 0, 0, 0))

    assert result is False
    with m._conn() as connection:
        raw_deadline = connection.execute(
            "SELECT cooldown_until FROM profiles WHERE id=7"
        ).fetchone()[0]
    deadline = datetime.fromisoformat(str(raw_deadline))
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    assert deadline >= before + timedelta(hours=47)


def test_provider_ack_is_not_retried_when_legacy_accounting_fails(
    tmp_path, monkeypatch
) -> None:
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    import app.campaign_send as campaign_send
    from app.campaign_send import send_with_retry

    gateway = _FakeGateway()
    _install_common_send_fakes(m, monkeypatch, gateway, max_retry=3)
    monkeypatch.setattr(
        campaign_send,
        "_persist_send_outcome",
        lambda **_kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("fixture write failure")),
    )

    result = asyncio.run(send_with_retry(profile, group, "fixture text", 0, 0, 0, 0))

    assert result is True
    assert gateway.send_calls == 1
    with m._conn() as connection:
        operation = connection.execute(
            "SELECT status, provider_message_id FROM operations"
        ).fetchone()
    assert tuple(operation) == ("accepted", "provider-77")


def test_post_ack_housekeeping_error_cannot_downgrade_operation(
    tmp_path, monkeypatch
) -> None:
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import send_with_retry

    gateway = _FakeGateway()
    _install_common_send_fakes(m, monkeypatch, gateway)
    monkeypatch.setattr(
        m,
        "_on_success",
        lambda _profile_id: (_ for _ in ()).throw(RuntimeError("flood wait cleanup")),
    )

    result = asyncio.run(send_with_retry(profile, group, "fixture text", 0, 0, 0, 0))

    assert result is True
    assert gateway.send_calls == 1
    with m._conn() as connection:
        operation = connection.execute(
            "SELECT status, provider_message_id FROM operations"
        ).fetchone()
    assert tuple(operation) == ("accepted", "provider-77")


def test_pre_network_retry_reuses_operation_identity_and_text(tmp_path, monkeypatch) -> None:
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import send_with_retry

    class RetryGateway(_FakeGateway):
        def __init__(self) -> None:
            super().__init__()
            self._failed = False

        async def check_destination(self, *, chat_id: int) -> None:
            self.check_calls += 1
            if not self._failed:
                self._failed = True
                raise RuntimeError("proxy unavailable before send")

    gateway = RetryGateway()
    _install_common_send_fakes(m, monkeypatch, gateway, max_retry=2)

    result = asyncio.run(send_with_retry(profile, group, "fixture text", 0, 0, 0, 0))

    assert result is True
    with m._conn() as connection:
        operations = connection.execute(
            "SELECT o.operation_id, o.text, o.status, o.pre_effect_retry_count, "
            "(SELECT COUNT(*) FROM operation_attempts a "
            " WHERE a.operation_id=o.operation_id) AS attempt_count "
            "FROM operations o"
        ).fetchall()
    assert len(operations) == 1
    assert tuple(operations[0][1:]) == ("fixture text", "accepted", 1, 1)
    assert gateway.check_calls == 2
    assert gateway.send_calls == 1


def test_timeout_after_in_flight_is_unknown_and_not_retried(tmp_path, monkeypatch) -> None:
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import send_with_retry

    gateway = _FakeGateway(send_error=TimeoutError("request timeout after transmit"))
    _install_common_send_fakes(m, monkeypatch, gateway, max_retry=3)

    result = asyncio.run(send_with_retry(profile, group, "fixture text", 0, 0, 0, 0))

    assert result is False
    assert gateway.send_calls == 1
    with m._conn() as connection:
        operation = connection.execute(
            "SELECT status, provider_message_id FROM operations"
        ).fetchone()
        attempt = connection.execute(
            "SELECT state FROM operation_attempts"
        ).fetchone()
    assert tuple(operation) == ("unknown", "")
    assert attempt["state"] == "unknown"


def test_flood_wait_after_in_flight_is_unknown_and_not_retried(
    tmp_path, monkeypatch
) -> None:
    """T12-C02/T13-C07: a post-boundary wait cannot authorize a replay."""
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import send_with_retry

    gateway = _FakeGateway(send_error=RuntimeError("flood wait 7200 seconds"))
    _install_common_send_fakes(m, monkeypatch, gateway, max_retry=3)

    result = asyncio.run(send_with_retry(profile, group, "fixture text", 0, 0, 0, 0))

    assert result is False
    assert gateway.send_calls == 1
    with m._conn() as connection:
        operation = connection.execute(
            "SELECT status FROM operations"
        ).fetchone()
        attempt = connection.execute(
            "SELECT state FROM operation_attempts"
        ).fetchone()
        cooldown = connection.execute(
            "SELECT cooldown_until FROM profiles WHERE id=7"
        ).fetchone()[0]
    assert operation["status"] == "unknown"
    assert attempt["state"] == "unknown"
    assert cooldown


@pytest.mark.parametrize(
    "failure",
    ("session_revoked", "confirmed_rejection", "confirmed_wait", "transport_ambiguity"),
)
def test_adapter_failure_matrix_preserves_conservative_operation_state(
    tmp_path, monkeypatch, failure
) -> None:
    """A05/R01: adapter failures never turn an unsafe result into a retry."""
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import send_with_retry

    class DestinationReviewError(RuntimeError):
        code = "DESTINATION_REVIEW_REQUIRED"

    class FailureGateway:
        def __init__(self) -> None:
            self.check_calls = 0
            self.send_calls = 0

        async def check_destination(self, *, chat_id: int) -> None:
            self.check_calls += 1
            if failure == "session_revoked":
                raise RuntimeError("session revoked")
            if failure == "confirmed_rejection":
                raise DestinationReviewError("destination review required")
            if failure == "confirmed_wait":
                raise RuntimeError("flood wait 3600 seconds")

        async def send_message(self, *, chat_id: int, text: str):
            self.send_calls += 1
            if failure == "transport_ambiguity":
                raise TimeoutError("request timeout after transmit")
            return SimpleNamespace(message_id="fixture-failure-matrix")

    gateway = FailureGateway()
    _install_common_send_fakes(
        m,
        monkeypatch,
        gateway,
        max_retry=2 if failure == "session_revoked" else 1,
    )
    result = asyncio.run(send_with_retry(profile, group, "fixture text", 0, 0, 0, 0))

    assert result is False
    with m._conn() as connection:
        operation = connection.execute(
            "SELECT operation_id, status FROM operations"
        ).fetchone()
        send_log = connection.execute(
            "SELECT status FROM send_log"
        ).fetchone()
        profile_after = connection.execute(
            "SELECT status, cooldown_until FROM profiles WHERE id=7"
        ).fetchone()
    if failure == "transport_ambiguity":
        assert operation["status"] == "unknown"
        assert send_log["status"] == "unknown"
        assert profile_after["status"] == "active"
        from app.repositories.operations import OperationRepository
        from app.services.operations import OperationLedger, OperationNotRetryable

        with m._conn() as connection:
            with pytest.raises(OperationNotRetryable):
                OperationLedger(OperationRepository(connection)).retry(
                    operation["operation_id"], proof_no_send=True
                )
        assert gateway.check_calls == 1
        assert gateway.send_calls == 1
    else:
        assert operation["status"] == "failed_unsent"
        assert send_log is None or send_log["status"] == "failed"
        assert gateway.check_calls == (2 if failure == "session_revoked" else 1)
        assert gateway.send_calls == 0
        if failure == "session_revoked":
            assert profile_after["status"] == "needs_reauth"
        else:
            assert profile_after["status"] == "active"
        if failure == "confirmed_wait":
            assert profile_after["cooldown_until"]


def test_cancellation_before_in_flight_keeps_operation_retryable(
    tmp_path, monkeypatch
) -> None:
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import SendTracker, send_with_retry

    started = asyncio.Event()
    blocked = asyncio.Event()

    class BlockingGateway(_FakeGateway):
        async def check_destination(self, *, chat_id: int) -> None:
            self.check_calls += 1
            started.set()
            await blocked.wait()

    gateway = BlockingGateway()
    _install_common_send_fakes(m, monkeypatch, gateway)
    tracker = SendTracker()

    async def _run() -> None:
        task = asyncio.create_task(
            send_with_retry(profile, group, "fixture text", 0, 0, 0, 0, tracker=tracker)
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_run())

    assert tracker.may_requeue is True
    assert gateway.send_calls == 0
    with m._conn() as connection:
        operation = connection.execute("SELECT status FROM operations").fetchone()
    assert operation["status"] == "failed_unsent"


def test_cancellation_after_in_flight_marks_unknown_without_retry(
    tmp_path, monkeypatch
) -> None:
    m, profile, group = _setup_local_db(tmp_path, monkeypatch)
    from app.campaign_send import SendTracker, send_with_retry

    started = asyncio.Event()
    blocked = asyncio.Event()

    class BlockingGateway(_FakeGateway):
        async def send_message(self, *, chat_id: int, text: str):
            self.send_calls += 1
            started.set()
            await blocked.wait()

    gateway = BlockingGateway()
    _install_common_send_fakes(m, monkeypatch, gateway, max_retry=3)
    tracker = SendTracker()

    async def _run() -> None:
        task = asyncio.create_task(
            send_with_retry(profile, group, "fixture text", 0, 0, 0, 0, tracker=tracker)
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_run())

    assert tracker.may_requeue is False
    assert gateway.send_calls == 1
    with m._conn() as connection:
        operation = connection.execute("SELECT status FROM operations").fetchone()
        attempt = connection.execute("SELECT state FROM operation_attempts").fetchone()
    assert operation["status"] == "unknown"
    assert attempt["state"] == "unknown"


def test_worker_start_recovery_marks_abandoned_operation_unknown(tmp_path, monkeypatch) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    from app.repositories.operations import OperationRepository
    from app.services.operations import OperationLedger

    with m._conn() as connection:
        ledger = OperationLedger(OperationRepository(connection))
        operation = ledger.create_operation(
            scope="local",
            profile_id=7,
            group_id=3,
            text="abandoned fixture",
            budget_date=m._local_today().isoformat(),
            route_snapshot={"group_id": 3, "chat_id": "77"},
            max_pre_effect_retries=1,
        )
        ledger.claim(operation.operation_id, profile_id=7)
        ledger.mark_in_flight(operation.operation_id, route_snapshot={"chat_id": "77"})

    from app.campaign_send import recover_inflight_operations

    assert recover_inflight_operations() == [operation.operation_id]
    with m._conn() as connection:
        recovered = connection.execute(
            "SELECT status FROM operations WHERE operation_id=?",
            (operation.operation_id,),
        ).fetchone()
    assert recovered["status"] == "unknown"


def test_start_worker_runs_recovery_before_preflight(tmp_path, monkeypatch) -> None:
    m, _profile, _group = _setup_local_db(tmp_path, monkeypatch)
    import app.campaign_worker as campaign_worker

    calls: list[str] = []

    monkeypatch.setattr(
        campaign_worker,
        "recover_inflight_operations",
        lambda: calls.append("recover") or ["op-recovered"],
    )
    monkeypatch.setattr(
        campaign_worker.main,
        "_preflight_group_proxies",
        lambda: calls.append("preflight") or asyncio.sleep(0),
    )
    monkeypatch.setattr(campaign_worker, "pool_supervisor", lambda: asyncio.sleep(0))
    monkeypatch.setattr(campaign_worker.main, "append_log", lambda _message: None)

    async def _run() -> None:
        assert await campaign_worker.start_worker(record_campaign=False) is True
        runtime = campaign_worker.REGISTRY.worker_for(None)
        if runtime.worker_task is not None:
            await runtime.worker_task

    asyncio.run(_run())

    assert calls == ["recover", "preflight"]
