"""ADR 007: global admin pacing settings copy into tenant SQLite."""

from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.settings_scope import (
    GLOBAL_PACING_LEGACY_INACTIVE,
    GLOBAL_PACING_NEVER_COPY,
    GLOBAL_PACING_SETTING_KEYS,
    filter_pacing_updates,
)
from app.tenant import clear_context, set_context, tenant_scope


def _setup_server_main(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-min-32-characters-long")
    monkeypatch.setenv("WEBHOOK_ALLOWED_HOSTS", "global.example")

    import app.config as cfg

    importlib.reload(cfg)
    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    m._refresh_data_paths()
    m.reset_test_runtime()
    return m


def _init_global(m) -> None:
    from app.tenant_init import ensure_global_data

    ensure_global_data(m.ROOT)
    with tenant_scope(use_global_data=True, role="admin"):
        m.init_db()


def _init_tenant(m, tenant_id: int) -> None:
    from app.tenant_init import init_tenant_db

    init_tenant_db(m, tenant_id)


def test_settings_in_delay_min_floor():
    from app.routes_models import SettingsIn

    with pytest.raises(ValidationError):
        SettingsIn(delay_min_sec=1)
    with pytest.raises(ValidationError):
        SettingsIn(delay_max_sec=1)
    assert SettingsIn(delay_min_sec=5).delay_min_sec == 5
    assert SettingsIn(delay_max_sec=5).delay_max_sec == 5


def test_runtime_timezone_is_fixed_to_utc_plus_three(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_tenant(m, 1)
    with tenant_scope(tenant_id=1, role="admin"):
        m.set_setting("timezone_offset_hours", "-8")
        expected = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
        assert abs((m._local_now() - expected).total_seconds()) < 2


def test_allowlist_classifies_every_default_key():
    import main as m

    assert GLOBAL_PACING_SETTING_KEYS.isdisjoint(GLOBAL_PACING_NEVER_COPY)
    assert (
        set(m.DEFAULTS)
        == GLOBAL_PACING_SETTING_KEYS
        | GLOBAL_PACING_NEVER_COPY
        | GLOBAL_PACING_LEGACY_INACTIVE
    )
    for secret in (
        "api_pin",
        "telegram_bot_token",
        "webhook_url",
        "auto_run",
        "worker_pool_size",
    ):
        assert secret in GLOBAL_PACING_NEVER_COPY
        assert secret not in GLOBAL_PACING_SETTING_KEYS


def test_filter_pacing_updates_drops_secrets():
    out = filter_pacing_updates(
        {
            "delay_min_sec": 9,
            "api_pin": "1234",
            "telegram_bot_token": "tok",
            "webhook_url": "https://evil.example",
            "auto_run": "1",
            "worker_pool_size": 8,
        }
    )
    assert out == {"delay_min_sec": "9"}


def test_admin_put_settings_changes_tenant_get_setting(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_global(m)
    _init_tenant(m, 11)
    _init_tenant(m, 12)

    from app.routes_models import SettingsIn
    from app.routes_settings import update_settings

    set_context(user_id=1, role="admin", use_global_data=True)
    try:
        asyncio.run(update_settings(SettingsIn(delay_min_sec=9, delay_max_sec=21)))
    finally:
        clear_context()

    with tenant_scope(tenant_id=11, role="user"):
        assert m.get_setting("delay_min_sec") == "9"
        assert m.get_setting("delay_max_sec") == "21"
    with tenant_scope(tenant_id=12, role="user"):
        assert m.get_setting("delay_min_sec") == "9"
        assert m.get_setting("delay_max_sec") == "21"
    with tenant_scope(use_global_data=True, role="admin"):
        assert m.get_setting("delay_min_sec") == "9"


def test_global_policy_revision_reports_partial_tenant_failure(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_global(m)
    _init_tenant(m, 11)
    _init_tenant(m, 12)

    import app.settings_scope as settings_scope

    original_apply = settings_scope._apply_pacing_revision_to_connection

    def fail_tenant_12(conn, **kwargs):
        from app.tenant import get_tenant_id

        if get_tenant_id() == 12:
            raise RuntimeError("controlled tenant failure")
        return original_apply(conn, **kwargs)

    monkeypatch.setattr(
        settings_scope,
        "_apply_pacing_revision_to_connection",
        fail_tenant_12,
    )

    from app.routes_models import SettingsIn
    from app.routes_settings import update_settings

    set_context(user_id=1, role="admin", use_global_data=True)
    try:
        result = asyncio.run(update_settings(SettingsIn(jitter_percent=33)))
    finally:
        clear_context()

    revision = result["policy_revision"]
    assert revision["partial"] is True
    assert revision["applied_tenants"] == [11]
    assert revision["failed_tenants"] == [
        {"tenant_id": 12, "safe_error": "tenant_apply_failed"}
    ]
    desired = int(revision["desired_revision"])
    assert revision["applied_revision"] == {
        "global": desired,
        "tenant:11": desired,
    }

    with tenant_scope(tenant_id=11, role="user"):
        assert m.get_setting("jitter_percent") == "33"
        state = m._conn().execute(
            "SELECT desired_revision, applied_revision FROM policy_scope_state "
            "WHERE scope_key='tenant:11'"
        ).fetchone()
        assert dict(state) == {
            "desired_revision": desired,
            "applied_revision": desired,
        }
    with tenant_scope(tenant_id=12, role="user"):
        assert m.get_setting("jitter_percent") == m.DEFAULTS["jitter_percent"]

    with tenant_scope(use_global_data=True, role="admin"):
        state = m._conn().execute(
            "SELECT desired_revision, applied_revision FROM policy_scope_state "
            "WHERE scope_key='global'"
        ).fetchone()
        assert dict(state) == {
            "desired_revision": desired,
            "applied_revision": desired,
        }
        outcomes = m._conn().execute(
            "SELECT tenant_id, status, safe_error FROM policy_apply_results "
            "WHERE version_id=? ORDER BY tenant_id",
            (desired,),
        ).fetchall()
        assert [dict(row) for row in outcomes] == [
            {"tenant_id": 11, "status": "applied", "safe_error": ""},
            {"tenant_id": 12, "status": "failed", "safe_error": "tenant_apply_failed"},
        ]


def test_partial_policy_retry_and_stop_start_preserve_v1_plans_and_revocation(
    tmp_path, monkeypatch, caplog
):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_global(m)
    _init_tenant(m, 11)
    _init_tenant(m, 12)

    from app.repositories.daily_plans import DailyPlanRepository
    from app.routes_campaign import CampaignCommandCoordinator, build_readiness
    from app.routes_models import SettingsIn
    from app.routes_settings import update_settings
    from app.services.daily_plans import DailyPlanService, LibraryItem

    set_context(user_id=1, role="admin", use_global_data=True)
    try:
        v1_result = asyncio.run(
            update_settings(SettingsIn(daily_limit_min=2, daily_limit_max=2))
        )
    finally:
        clear_context()
    v1_revision = int(v1_result["policy_revision"]["desired_revision"])

    plan_date = "2026-09-23"
    v1_items = (
        LibraryItem("v1-item-1", "fixture text one", "library-v1"),
        LibraryItem("v1-item-2", "fixture text two", "library-v1"),
    )
    plan_snapshots = {}
    for tenant_id in (11, 12):
        with tenant_scope(tenant_id=tenant_id, role="admin"):
            service = DailyPlanService(DailyPlanRepository(m._conn()))
            plan = service.materialize_day(
                f"tenant:{tenant_id}",
                7,
                plan_date,
                sampled_limit=2,
                role="active",
                quiet_limit=2,
                work_group_id=3,
                library_items=v1_items,
                mode="round_robin",
            )
            assert plan.target == 2
            assert plan.version_id == "library-v1"
            plan_snapshots[tenant_id] = plan

    import app.settings_scope as settings_scope

    original_apply = settings_scope._apply_pacing_revision_to_connection
    fail_tenant_12 = [True]

    def fail_tenant_12_once(conn, **kwargs):
        if kwargs["scope_key"] == "tenant:12" and fail_tenant_12[0]:
            fail_tenant_12[0] = False
            raise RuntimeError("api_token=fixture-private-value")
        return original_apply(conn, **kwargs)

    monkeypatch.setattr(
        settings_scope,
        "_apply_pacing_revision_to_connection",
        fail_tenant_12_once,
    )

    set_context(user_id=1, role="admin", use_global_data=True)
    try:
        v2_result = asyncio.run(
            update_settings(
                SettingsIn(
                    delay_min_sec=60,
                    delay_max_sec=120,
                    daily_limit_min=9,
                    daily_limit_max=9,
                )
            )
        )
    finally:
        clear_context()

    partial = v2_result["policy_revision"]
    v2_revision = int(partial["desired_revision"])
    assert v2_revision > v1_revision
    assert partial["partial"] is True
    assert partial["applied_tenants"] == [11]
    assert partial["failed_tenants"] == [
        {"tenant_id": 12, "safe_error": "tenant_apply_failed"}
    ]
    with tenant_scope(use_global_data=True, role="admin"):
        global_state = m._conn().execute(
            "SELECT desired_revision, applied_revision FROM policy_scope_state "
            "WHERE scope_key='global'"
        ).fetchone()
        assert tuple(global_state) == (v2_revision, v2_revision)
    with tenant_scope(tenant_id=11, role="admin"):
        tenant_11_state = m._conn().execute(
            "SELECT desired_revision, applied_revision FROM policy_scope_state "
            "WHERE scope_key='tenant:11'"
        ).fetchone()
        assert tuple(tenant_11_state) == (v2_revision, v2_revision)
        assert m.get_setting("daily_limit_max") == "9"
    with tenant_scope(tenant_id=12, role="admin"):
        tenant_12_state = m._conn().execute(
            "SELECT desired_revision, applied_revision FROM policy_scope_state "
            "WHERE scope_key='tenant:12'"
        ).fetchone()
        assert tuple(tenant_12_state) == (v1_revision, v1_revision)
        assert m.get_setting("daily_limit_max") == "2"

    from app.settings_scope import propagate_global_pacing_settings

    retried = propagate_global_pacing_settings(
        {
            "delay_min_sec": 60,
            "delay_max_sec": 120,
            "daily_limit_min": 9,
            "daily_limit_max": 9,
            "max_msgs_per_profile_day": 9,
        },
        desired_revision=v2_revision,
        actor=1,
    )
    retry_report = retried.as_dict()
    assert retry_report["desired_revision"] == v2_revision
    assert retry_report["partial"] is False
    assert retry_report["applied_tenants"] == [11, 12]
    assert retry_report["applied_revision"] == {
        "global": v2_revision,
        "tenant:11": v2_revision,
        "tenant:12": v2_revision,
    }
    assert "fixture-private-value" not in caplog.text

    for tenant_id in (11, 12):
        with tenant_scope(tenant_id=tenant_id, role="admin"):
            connection = m._conn()
            repository = DailyPlanRepository(connection)
            cancelled = repository.cancel_queued_for_profile(
                f"tenant:{tenant_id}", 7, "CONSENT_REVOKED"
            )
            assert cancelled == 2
            assert repository.count_slots(f"tenant:{tenant_id}", "queued") == 0
            assert repository.count_slots(f"tenant:{tenant_id}", "cancelled") == 2

            with connection:
                coordinator = CampaignCommandCoordinator(
                    connection, scope=f"tenant:{tenant_id}"
                )
                readiness = build_readiness(
                    version="policy-v2",
                    scope=f"tenant:{tenant_id}",
                    checks={"local_fixture_ready": True},
                )
                first = coordinator.begin_start(
                    f"rc10-start-before-stop-{tenant_id}", readiness
                )
                assert coordinator.complete_start(
                    f"rc10-start-before-stop-{tenant_id}"
                ).state == "running"
                stop = coordinator.stop(f"rc10-stop-{tenant_id}")
                assert stop.state == "stopping"
                assert coordinator.complete_stop(
                    f"rc10-stop-{tenant_id}"
                ).state == "stopped"
                second = coordinator.begin_start(
                    f"rc10-start-after-stop-{tenant_id}", readiness
                )
                assert second.generation > first.generation
                assert coordinator.complete_start(
                    f"rc10-start-after-stop-{tenant_id}"
                ).state == "running"

            service = DailyPlanService(DailyPlanRepository(connection))
            current = service.materialize_day(
                f"tenant:{tenant_id}",
                7,
                plan_date,
                sampled_limit=9,
                role="active",
                quiet_limit=9,
                work_group_id=3,
                library_items=(
                    LibraryItem("v2-item", "new text", "library-v2"),
                ),
                mode="round_robin",
            )
            assert current.plan_id == plan_snapshots[tenant_id].plan_id
            assert current.target == 2
            assert current.sampled_limit == 2
            assert current.version_id == "library-v1"
            assert repository.count_slots(f"tenant:{tenant_id}", "queued") == 0
            assert repository.count_slots(f"tenant:{tenant_id}", "cancelled") == 2

            state = connection.execute(
                "SELECT desired_revision, applied_revision FROM policy_scope_state "
                "WHERE scope_key=?",
                (f"tenant:{tenant_id}",),
            ).fetchone()
            assert tuple(state) == (v2_revision, v2_revision)
            assert m.get_setting("daily_limit_max") == "9"
            assert m.get_setting("delay_min_sec") == "60"


def test_global_scope_reuses_one_sqlite_connection(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_global(m)
    with tenant_scope(use_global_data=True, role="admin"):
        assert m._global_conn() is m._conn()


def test_secrets_and_ops_keys_not_copied_to_tenants(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_global(m)
    _init_tenant(m, 11)

    with tenant_scope(tenant_id=11, role="user"):
        m.set_setting("worker_pool_size", "3")
        m.set_setting("auto_run", "1")
        m.set_setting("webhook_url", "https://tenant-a.example")
        m.set_setting("api_pin", "tenant-pin")

    with tenant_scope(use_global_data=True, role="admin"):
        m.set_setting("api_pin", "global-pin")

    from app.routes_models import SettingsIn
    from app.routes_settings import update_settings

    set_context(user_id=1, role="admin", use_global_data=True)
    try:
        asyncio.run(
            update_settings(
                SettingsIn(
                    delay_min_sec=8,
                    telegram_bot_token="global-bot-token",
                    webhook_url="https://global.example",
                )
            )
        )
    finally:
        clear_context()

    with tenant_scope(tenant_id=11, role="user"):
        assert m.get_setting("delay_min_sec") == "8"
        assert m.get_setting("api_pin") == "tenant-pin"
        assert m.get_setting("telegram_bot_token") == ""
        assert m.get_setting("webhook_url") == "https://tenant-a.example"
        assert m.get_setting("worker_pool_size") == "3"
        assert m._pool_size() == 1
        assert m.get_setting("auto_run") == "1"
        assert m.get_setting("auto_run_pool_reset_day") == ""


def test_cross_tenant_unique_keys_not_copied(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_global(m)
    _init_tenant(m, 21)
    _init_tenant(m, 22)

    with tenant_scope(tenant_id=21, role="user"):
        m.set_setting("webhook_url", "https://tenant-a.example")
        m.set_setting("api_pin", "pin-a")
    with tenant_scope(tenant_id=22, role="user"):
        m.set_setting("webhook_url", "https://tenant-b.example")
        m.set_setting("api_pin", "pin-b")

    from app.routes_models import SettingsIn
    from app.routes_settings import update_settings

    set_context(user_id=1, role="admin", use_global_data=True)
    try:
        asyncio.run(update_settings(SettingsIn(jitter_percent=33)))
    finally:
        clear_context()

    with tenant_scope(tenant_id=21, role="user"):
        assert m.get_setting("jitter_percent") == "33"
        assert m.get_setting("webhook_url") == "https://tenant-a.example"
        assert m.get_setting("api_pin") == "pin-a"
    with tenant_scope(tenant_id=22, role="user"):
        assert m.get_setting("jitter_percent") == "33"
        assert m.get_setting("webhook_url") == "https://tenant-b.example"
        assert m.get_setting("api_pin") == "pin-b"


def test_new_tenant_init_seeds_from_global(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_global(m)
    with tenant_scope(use_global_data=True, role="admin"):
        m.set_setting("delay_min_sec", "42")
        m.set_setting("daily_limit_max", "7")
        m.set_setting("api_pin", "should-not-seed")
        m.set_setting("worker_pool_size", "5")
        m.set_setting("auto_run", "1")

    _init_tenant(m, 31)

    with tenant_scope(tenant_id=31, role="user"):
        assert m.get_setting("delay_min_sec") == "42"
        assert m.get_setting("daily_limit_max") == "7"
        assert m.get_setting("api_pin") == ""
        assert m.get_setting("worker_pool_size") == "1"
        assert m.get_setting("auto_run") == "0"
        assert m.get_setting("webhook_url") == ""


def test_new_tenant_init_uses_defaults_when_global_has_no_pacing(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_tenant(m, 41)

    with tenant_scope(tenant_id=41, role="user"):
        assert m.get_setting("delay_min_sec") == m.DEFAULTS["delay_min_sec"]
        assert m.get_setting("worker_pool_size") == m.DEFAULTS["worker_pool_size"]
        assert m.get_setting("auto_run") == m.DEFAULTS["auto_run"]


def test_existing_tenant_init_db_does_not_reseed(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_global(m)
    _init_tenant(m, 51)
    with tenant_scope(tenant_id=51, role="user"):
        m.set_setting("delay_min_sec", "17")
    with tenant_scope(use_global_data=True, role="admin"):
        m.set_setting("delay_min_sec", "99")
    with tenant_scope(tenant_id=51, role="user"):
        m.init_db()
        assert m.get_setting("delay_min_sec") == "17"


def test_tenant_scoped_put_does_not_fan_out(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_global(m)
    _init_tenant(m, 61)
    _init_tenant(m, 62)

    from app.routes_models import SettingsIn
    from app.routes_settings import update_settings

    set_context(user_id=1, tenant_id=61, role="admin", impersonating=True)
    try:
        asyncio.run(update_settings(SettingsIn(delay_min_sec=11)))
    finally:
        clear_context()

    with tenant_scope(tenant_id=61, role="user"):
        assert m.get_setting("delay_min_sec") == "11"
    with tenant_scope(tenant_id=62, role="user"):
        assert m.get_setting("delay_min_sec") == m.DEFAULTS["delay_min_sec"]


def test_partial_range_update_validates_against_stored_value(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_tenant(m, 71)
    with tenant_scope(tenant_id=71, role="user"):
        m.set_setting("delay_min_sec", "5")
        m.set_setting("delay_max_sec", "10")

    from app.routes_models import SettingsIn
    from app.routes_settings import update_settings

    set_context(user_id=1, tenant_id=71, role="admin", impersonating=True)
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(update_settings(SettingsIn(delay_min_sec=11)))
        assert exc.value.status_code == 400
        assert m.get_setting("delay_min_sec") == "5"
    finally:
        clear_context()


def test_global_partial_range_propagates_coherent_pair(tmp_path, monkeypatch):
    m = _setup_server_main(tmp_path, monkeypatch)
    _init_global(m)
    _init_tenant(m, 72)
    with tenant_scope(use_global_data=True, role="admin"):
        m.set_setting("delay_min_sec", "5")
        m.set_setting("delay_max_sec", "20")
    with tenant_scope(tenant_id=72, role="user"):
        m.set_setting("delay_min_sec", "5")
        m.set_setting("delay_max_sec", "8")

    from app.routes_models import SettingsIn
    from app.routes_settings import update_settings

    set_context(user_id=1, role="admin", use_global_data=True)
    try:
        asyncio.run(update_settings(SettingsIn(delay_min_sec=10)))
    finally:
        clear_context()

    with tenant_scope(tenant_id=72, role="user"):
        assert m.get_setting("delay_min_sec") == "10"
        assert m.get_setting("delay_max_sec") == "20"


def test_revoke_subscription_route_requires_admin():
    from app.routes_admin import router, revoke_subscription

    paths = [getattr(r, "path", "") for r in router.routes]
    assert any("subscription/revoke" in p for p in paths)

    set_context(user_id=2, tenant_id=1, role="user")
    try:
        with pytest.raises(HTTPException) as ei:
            asyncio.run(revoke_subscription(1))
        assert ei.value.status_code == 403
    finally:
        clear_context()
