"""ADR 007: global admin pacing settings copy into tenant SQLite."""

from __future__ import annotations

import asyncio
import importlib

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.settings_scope import (
    GLOBAL_PACING_NEVER_COPY,
    GLOBAL_PACING_SETTING_KEYS,
    filter_pacing_updates,
)
from app.tenant import clear_context, set_context, tenant_scope


def _setup_server_main(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_SERVER_MODE", "1")
    monkeypatch.setenv("MAX_TEST", "1")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-min-32-characters-long")

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


def test_allowlist_classifies_every_default_key():
    import main as m

    assert GLOBAL_PACING_SETTING_KEYS.isdisjoint(GLOBAL_PACING_NEVER_COPY)
    assert set(m.DEFAULTS) == GLOBAL_PACING_SETTING_KEYS | GLOBAL_PACING_NEVER_COPY
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
                    worker_pool_size=16,
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
