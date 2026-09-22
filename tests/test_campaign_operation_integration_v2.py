"""T12 integration: the legacy send path must use one durable operation."""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

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
            "INSERT INTO groups (id, name, max_chat_id, is_active) VALUES (3, 'fixture', '77', 1)"
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
