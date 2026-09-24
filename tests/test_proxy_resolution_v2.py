"""T04: persisted route assignments are stable and fail closed."""

from __future__ import annotations

import sqlite3

import pytest


def _catalog():
    from app.repositories.connections import ConnectionRepository

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    repo = ConnectionRepository(conn)
    repo.ensure_schema()
    return conn, repo


def test_initial_assignment_is_stable_when_catalog_order_changes() -> None:
    from app.services.proxies import resolve_route

    _conn, repo = _catalog()
    repo.add_connection(2, scheme="socks5", host="p2.example", port=1080, credential_ref="cred-2")
    repo.add_connection(5, scheme="socks5", host="p5.example", port=1080, credential_ref="cred-5")
    repo.add_group_connection(10, 2)
    repo.add_group_connection(10, 5)

    first = resolve_route("tenant:1", 1, 10, "send", catalog=repo)
    assert first.connection_id == 2

    repo.reorder_connections((5, 2))
    second = resolve_route("tenant:1", 1, 10, "login", catalog=repo)
    assert second.connection_id == first.connection_id
    assert second.version == first.version


def test_assigned_route_is_shared_by_login_and_send_until_explicit_change() -> None:
    from app.services.proxies import resolve_route

    conn, repo = _catalog()
    try:
        repo.add_connection(2, scheme="socks5", host="p2.example", port=1080, credential_ref="cred-2")
        repo.add_connection(3, scheme="socks5", host="p3.example", port=1080, credential_ref="cred-3")
        repo.add_group_connection(10, 2)
        repo.add_group_connection(10, 3)
        repo.assign_route(7, 10, 2)

        login = resolve_route("tenant:1", 7, 10, "login", catalog=repo)
        send = resolve_route("tenant:1", 7, 10, "send", catalog=repo)

        assert login.connection_id == 2
        assert send.connection_id == login.connection_id
        assert send.version == login.version
    finally:
        conn.close()


def test_catalog_growth_preserves_thirty_assignments_and_single_sender() -> None:
    from app.services.proxies import resolve_route

    conn, repo = _catalog()
    try:
        for connection_id in range(1, 6):
            repo.add_connection(
                connection_id,
                scheme="socks5",
                host=f"p{connection_id}.example",
                port=1080,
                credential_ref=f"cred-{connection_id}",
            )
            repo.add_group_connection(10, connection_id)

        initial = {
            profile_id: resolve_route("tenant:1", profile_id, 10, "send", catalog=repo).connection_id
            for profile_id in range(1, 31)
        }

        repo.add_connection(6, scheme="socks5", host="p6.example", port=1080, credential_ref="cred-6")
        repo.add_group_connection(10, 6)
        repo.reorder_connections((6, 5, 4, 3, 2, 1))
        after_growth = {
            profile_id: resolve_route("tenant:1", profile_id, 10, "send", catalog=repo).connection_id
            for profile_id in initial
        }

        assert after_growth == initial
        assert repo.conn.execute(
            "SELECT COUNT(*) FROM profile_route_assignments"
        ).fetchone()[0] == 30

        import main

        assert main._pool_size() == 1
    finally:
        conn.close()


def test_missing_work_group_is_explicit_and_does_not_choose_minimum() -> None:
    from app.services.errors import classify_exception
    from app.services.proxies import RouteResolutionError, resolve_route

    _conn, repo = _catalog()
    repo.add_connection(1, scheme="socks5", host="p1.example", port=1080, credential_ref="cred-1")
    repo.add_connection(2, scheme="socks5", host="p2.example", port=1080, credential_ref="cred-2")
    repo.add_group_connection(10, 1)
    repo.add_group_connection(20, 2)
    repo.add_profile_group(7, 10)
    repo.add_profile_group(7, 20)

    with pytest.raises(RouteResolutionError) as caught:
        resolve_route("tenant:1", 7, None, "send", catalog=repo)
    assert caught.value.code == "WORK_GROUP_SELECTION_REQUIRED"
    safe = classify_exception(caught.value, source="storage", stage="route", outcome="rejected")
    assert safe.code == "WORK_GROUP_SELECTION_REQUIRED"


def test_disabled_assigned_route_has_no_direct_or_alternate_fallback() -> None:
    from app.services.proxies import RouteResolutionError, resolve_route

    _conn, repo = _catalog()
    repo.add_connection(4, scheme="socks5", host="p4.example", port=1080, credential_ref="cred-4")
    repo.add_connection(8, scheme="socks5", host="p8.example", port=1080, credential_ref="cred-8")
    repo.add_group_connection(10, 4)
    repo.add_group_connection(10, 8)
    repo.assign_route(7, 10, 4)
    repo.set_connection_enabled(4, False)

    with pytest.raises(RouteResolutionError) as caught:
        resolve_route("tenant:1", 7, 10, "send", catalog=repo)
    assert caught.value.code == "ROUTE_DISABLED"
    assert repo.assignment_for(7)["connection_id"] == 4


def test_server_legacy_direct_proxy_is_rejected_without_assignment() -> None:
    from app.services.proxies import RouteResolutionError, resolve_route

    conn, repo = _catalog()
    conn.execute("CREATE TABLE profiles (id INTEGER PRIMARY KEY, proxy TEXT)")
    conn.execute("INSERT INTO profiles(id, proxy) VALUES (7, 'socks5://legacy.example:1080')")
    conn.commit()

    with pytest.raises(RouteResolutionError) as caught:
        resolve_route("tenant:1", 7, 10, "send", catalog=repo, server_mode=True)
    assert caught.value.code == "ROUTE_CONFLICT"


def test_legacy_route_dry_run_requires_resolution_without_mutation() -> None:
    from app.services.proxies import legacy_route_migration_report

    conn, repo = _catalog()
    try:
        conn.execute("CREATE TABLE profiles (id INTEGER PRIMARY KEY, proxy TEXT)")
        conn.execute(
            "INSERT INTO profiles(id, proxy) VALUES (7, 'socks5://legacy.example:1080')"
        )
        conn.commit()

        report = legacy_route_migration_report(repo)

        assert report == [
            {
                "profile_id": 7,
                "status": "REVIEW_REQUIRED",
                "reason": "LEGACY_DIRECT_ROUTE",
                "assignment_present": False,
                "requires_explicit_resolution": True,
                "writes": 0,
                "probe_calls": 0,
                "login_calls": 0,
            }
        ]
        assert conn.execute(
            "SELECT proxy FROM profiles WHERE id=7"
        ).fetchone()[0] == "socks5://legacy.example:1080"
        assert conn.execute(
            "SELECT COUNT(*) FROM profile_route_assignments"
        ).fetchone()[0] == 0
    finally:
        conn.close()
