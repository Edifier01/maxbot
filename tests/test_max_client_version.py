"""Existing-session identity is explicit and never regenerated on connect."""

from pymax import ExtraConfig
from pymax.versions.catalog import VersionCatalog

from app.services.pymax_runtime import (
    PyMaxSessionIdentity,
    build_extra_config,
)


def test_existing_identity_is_passed_without_user_agent_generation(monkeypatch):
    catalog = VersionCatalog(remote=False)
    app_version = VersionCatalog.RECOMMENDED_APP_VERSION
    fingerprint = catalog.resolve(app_version)
    fixture_extra = ExtraConfig(reconnect=False, telemetry=False)
    identity = PyMaxSessionIdentity(
        device_id="device-1",
        mt_instance_id="instance-1",
        user_agent=fixture_extra.generate_user_agent(
            app_version,
            fingerprint.build_number,
        ),
        migrated=False,
    )

    def fail_generation(*_args, **_kwargs):
        raise AssertionError("existing-session path must not generate a user-agent")

    monkeypatch.setattr(ExtraConfig, "generate_user_agent", fail_generation)
    extra = build_extra_config(proxy=None, identity=identity)

    assert extra.device_id == "device-1"
    assert extra.mt_instance_id == "instance-1"
    assert extra.user_agent == identity.user_agent
    assert extra.reconnect is False
    assert extra.relogin is False
    assert extra.telemetry is False


def test_identity_is_not_replaced_by_catalog_defaults(monkeypatch):
    catalog = VersionCatalog(remote=False)
    app_version = VersionCatalog.RECOMMENDED_APP_VERSION
    fingerprint = catalog.resolve(app_version)
    fixture_extra = ExtraConfig(reconnect=False, telemetry=False)
    identity = PyMaxSessionIdentity(
        device_id="device-2",
        mt_instance_id="instance-2",
        user_agent=fixture_extra.generate_user_agent(
            app_version,
            fingerprint.build_number,
        ),
        migrated=False,
    )

    monkeypatch.setattr(
        ExtraConfig,
        "generate_user_agent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected user-agent generation")
        ),
    )
    extra = build_extra_config(proxy="socks5://fixture.example:1080", identity=identity)
    assert extra.user_agent is identity.user_agent
