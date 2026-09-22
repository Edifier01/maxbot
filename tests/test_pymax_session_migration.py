import asyncio
import re
import sqlite3

from pymax import ExtraConfig

from app.services.pymax_runtime import build_extra_config, ensure_session_identity


LEGACY_SCHEMA = """
CREATE TABLE sessions (
    token TEXT NOT NULL PRIMARY KEY,
    device_id TEXT NOT NULL,
    phone TEXT NOT NULL,
    mt_instance_id TEXT NOT NULL DEFAULT '',
    chats_sync INTEGER NOT NULL DEFAULT -1,
    contacts_sync INTEGER NOT NULL DEFAULT -1,
    drafts_sync INTEGER NOT NULL DEFAULT -1,
    presence_sync INTEGER NOT NULL DEFAULT -1,
    config_hash TEXT NOT NULL DEFAULT ''
)
"""


def test_v240_session_gets_one_persisted_identity(tmp_path) -> None:
    db = tmp_path / "session.db"
    with sqlite3.connect(db) as conn:
        conn.execute(LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("fixture-token", "device-1", "+70000000000", "instance-1", 4, 5, 6, 7, "cfg"),
        )

    first_identity = asyncio.run(ensure_session_identity(tmp_path, "session.db"))
    assert first_identity.migrated is True
    with sqlite3.connect(db) as conn:
        first = conn.execute(
            "SELECT token, device_id, phone, mt_instance_id, chats_sync, contacts_sync, "
            "drafts_sync, presence_sync, config_hash, user_agent FROM sessions"
        ).fetchone()

    second_identity = asyncio.run(ensure_session_identity(tmp_path, "session.db"))
    assert second_identity.migrated is False
    with sqlite3.connect(db) as conn:
        second = conn.execute(
            "SELECT token, device_id, phone, mt_instance_id, chats_sync, contacts_sync, "
            "drafts_sync, presence_sync, config_hash, user_agent FROM sessions"
        ).fetchone()

    assert first == second
    assert first[:9] == (
        "fixture-token",
        "device-1",
        "+70000000000",
        "instance-1",
        4,
        5,
        6,
        7,
        "cfg",
    )
    assert first[9]
    assert first_identity.user_agent == second_identity.user_agent

    extra = build_extra_config(proxy=None, identity=second_identity)
    assert extra.device_id == "device-1"
    assert extra.mt_instance_id == "instance-1"
    assert extra.user_agent == second_identity.user_agent


def test_legacy_empty_instance_id_is_generated_once(tmp_path) -> None:
    db = tmp_path / "session.db"
    with sqlite3.connect(db) as conn:
        conn.execute(LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("fixture-token", "device-2", "+70000000001", "", 1, 2, 3, 4, "cfg"),
        )

    first = asyncio.run(ensure_session_identity(tmp_path, "session.db"))
    second = asyncio.run(ensure_session_identity(tmp_path, "session.db"))

    assert first.migrated is True
    assert second.migrated is False
    assert re.fullmatch(r"[0-9a-f]{16}", first.mt_instance_id)
    assert second.mt_instance_id == first.mt_instance_id


def test_existing_user_agent_keeps_device_characteristics(monkeypatch, tmp_path) -> None:
    app_version = "26.24.0"
    fixture_extra = ExtraConfig(reconnect=False, telemetry=False)
    old_user_agent = fixture_extra.generate_user_agent(app_version, 6784)
    db = tmp_path / "session.db"
    with sqlite3.connect(db) as conn:
        conn.execute(LEGACY_SCHEMA)
        conn.execute("ALTER TABLE sessions ADD COLUMN user_agent TEXT")
        conn.execute(
            "INSERT INTO sessions (token, device_id, phone, mt_instance_id, chats_sync, "
            "contacts_sync, drafts_sync, presence_sync, config_hash, user_agent) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "fixture-token-2",
                "device-3",
                "+70000000002",
                "instance-3",
                8,
                9,
                10,
                11,
                "cfg-2",
                old_user_agent.model_dump_json(by_alias=True, exclude_none=True),
            ),
        )

    first = asyncio.run(ensure_session_identity(tmp_path, "session.db"))
    assert first.user_agent.model_dump(exclude={"app_version", "build_number"}) == old_user_agent.model_dump(
        exclude={"app_version", "build_number"}
    )

    def fail_generation(*_args, **_kwargs):
        raise AssertionError("existing user-agent must not be regenerated")

    monkeypatch.setattr(ExtraConfig, "generate_user_agent", fail_generation)
    second = asyncio.run(ensure_session_identity(tmp_path, "session.db"))
    extra = build_extra_config(proxy=None, identity=second)

    assert second.migrated is False
    assert extra.user_agent is second.user_agent
    assert extra.device_id == "device-3"
    assert extra.mt_instance_id == "instance-3"
