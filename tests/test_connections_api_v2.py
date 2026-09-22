"""T16: redacted connection summaries, route versions, and bounded probes."""

from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from app.repositories.connections import ConnectionRepository
from app.routes_connections import (
    ConnectionCatalog,
    ConnectionConflict,
    ProbeAlreadyRunning,
)


def _catalog() -> tuple[sqlite3.Connection, ConnectionCatalog]:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    repository = ConnectionRepository(connection)
    repository.ensure_schema()
    repository.add_connection(
        1, scheme="socks5", host="proxy.invalid", port=1080, credential_ref="vault:conn-1"
    )
    repository.add_group_connection(3, 1)
    repository.add_profile_group(7, 3)
    repository.assign_route(7, 3, 1)
    return connection, ConnectionCatalog(repository)


def test_user_summary_redacts_credentials_and_shows_assignments() -> None:
    connection, catalog = _catalog()
    try:
        rows = catalog.list_summaries(role="user")
        assert rows[0]["connection_id"] == 1
        assert "credential_ref" not in rows[0]
        assert "password" not in rows[0]
        assert rows[0]["assigned_profile_count"] == 1
    finally:
        connection.close()


def test_edit_requires_route_version_and_preserves_existing_assignment() -> None:
    connection, catalog = _catalog()
    try:
        current = catalog.list_summaries(role="admin")[0]
        updated = catalog.update_connection(
            1, expected_version=current["version"], host="proxy2.invalid"
        )
        assert updated["version"] == current["version"] + 1
        assert catalog.repository.assignment_for(7)["connection_id"] == 1
        with pytest.raises(ConnectionConflict):
            catalog.update_connection(1, expected_version=current["version"], host="stale.invalid")
    finally:
        connection.close()


def test_probe_result_is_versioned_and_does_not_report_otp_or_credentials() -> None:
    connection, catalog = _catalog()
    try:
        result = catalog.record_probe(
            1,
            route_version=1,
            result={
                "ok": True,
                "error_code": None,
                "stages": {"proxy_tcp": "PASS", "proxy_connect": "PASS"},
                "otp_calls": 0,
            },
        )
        assert result["valid_for_route_version"] == 1
        assert result["otp_calls"] == 0
        history = catalog.probe_history(1, limit=10)
        assert len(history) == 1
        assert "credential_ref" not in history[0]
        assert "password" not in history[0]
    finally:
        connection.close()


def test_duplicate_probe_is_bounded_to_one_fake_probe() -> None:
    connection, catalog = _catalog()
    calls: list[int] = []
    started = threading.Event()
    release = threading.Event()

    def fake_probe():
        calls.append(1)
        started.set()
        release.wait(timeout=2)
        return {"ok": True, "error_code": None, "stages": {"proxy_tcp": "PASS"}, "otp_calls": 0}

    try:
        first_result: list[object] = []

        def first() -> None:
            first_result.append(catalog.run_probe_once(1, route_version=1, probe=fake_probe))

        thread = threading.Thread(target=first)
        thread.start()
        assert started.wait(timeout=1)
        with pytest.raises(ProbeAlreadyRunning):
            catalog.run_probe_once(1, route_version=1, probe=fake_probe)
        release.set()
        thread.join(timeout=2)
        assert len(calls) == 1
        assert first_result[0]["otp_calls"] == 0
    finally:
        release.set()
        connection.close()
