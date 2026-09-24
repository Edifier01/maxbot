from importlib.metadata import version
from inspect import iscoroutinefunction, signature
from typing import get_type_hints

from pymax import Client, ExtraConfig, Message

from app.services.pymax_runtime import (
    PYMAX_REQUIRED_VERSION,
    build_extra_config,
    inspect_pymax_runtime,
)


def test_exact_pymax_241_contract() -> None:
    assert PYMAX_REQUIRED_VERSION == "2.4.1"
    assert version("maxapi-python") == PYMAX_REQUIRED_VERSION
    assert iscoroutinefunction(Client.connect)
    assert tuple(signature(ExtraConfig.generate_user_agent).parameters) == (
        "self",
        "app_version",
        "build_number",
    )
    assert get_type_hints(Client.send_message)["return"] is Message


def test_pymax_241_reaction_signature_matches_the_gateway_contract() -> None:
    assert iscoroutinefunction(Client.add_reaction)
    assert tuple(signature(Client.add_reaction).parameters) == (
        "self",
        "chat_id",
        "message_id",
        "reaction",
    )


def test_runtime_policy_is_fixed_and_quiet() -> None:
    info = inspect_pymax_runtime()
    extra = build_extra_config(proxy=None, identity=None)

    assert (info.tcp_host, info.tcp_port) == ("api2.oneme.ru", 443)
    assert info.remote_catalog is False
    assert extra.reconnect is False
    assert extra.relogin is False
    assert extra.telemetry is False
    assert extra.persist_session is True
