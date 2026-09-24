"""T33 worker-facing safeguards; no provider adapter is used."""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timezone

from app.repositories.daily_plans import DailyPlanRepository
from app.services.daily_plans import DailyPlanService, LibraryItem, WaitDecision


def test_unavailable_account_slot_is_not_transferred_to_another_account() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    service = DailyPlanService(DailyPlanRepository(connection))
    try:
        service.materialize_day(
            "tenant:1", 1, "2026-09-20", sampled_limit=1, role="active", quiet_limit=1,
            work_group_id=10,
            library_items=(LibraryItem("a", "account-a", "v1"),),
            rng=random.Random(1),
        )
        service.materialize_day(
            "tenant:1", 2, "2026-09-20", sampled_limit=1, role="active", quiet_limit=1,
            work_group_id=20,
            library_items=(LibraryItem("b", "account-b", "v1"),),
            rng=random.Random(1),
        )
        first = service.claim_next_slot(
            "tenant:1", datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
        )
        second = service.claim_next_slot(
            "tenant:1", datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
        )
        assert first.profile_id == 1
        assert second.profile_id == 2
        assert first.rendered_text == "account-a"
        assert second.rendered_text == "account-b"
    finally:
        connection.close()


def test_unauthorized_group_assignment_stays_queued_before_sdk_boundary() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    service = DailyPlanService(DailyPlanRepository(connection))
    try:
        service.materialize_day(
            "tenant:1", 1, "2026-09-20", sampled_limit=1, role="active", quiet_limit=1,
            work_group_id=10,
            library_items=(LibraryItem("a", "account-a", "v1"),),
            rng=random.Random(1),
        )
        decision = service.claim_next_slot(
            "tenant:1",
            datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc),
            eligible_assignments=((1, 20),),
        )
        assert isinstance(decision, WaitDecision)
        row = connection.execute(
            "SELECT s.status, p.work_group_id FROM profile_message_slots s "
            "JOIN profile_daily_plans p ON p.plan_id=s.plan_id"
        ).fetchone()
        assert tuple(row) == ("queued", 10)
    finally:
        connection.close()


def test_synthetic_topologies_preserve_group_proxy_plan_ownership() -> None:
    from app.repositories.connections import ConnectionRepository
    from app.services.proxies import resolve_route

    def run_topology(topology: tuple[tuple[int, range, range], ...]) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        catalog = ConnectionRepository(connection)
        catalog.ensure_schema()
        service = DailyPlanService(DailyPlanRepository(connection))
        expected: dict[int, tuple[int, int]] = {}
        try:
            for group_id, profile_ids, connection_ids in topology:
                for connection_id in connection_ids:
                    catalog.add_connection(
                        connection_id,
                        scheme="socks5",
                        host=f"proxy-{connection_id}.example",
                        port=1080,
                        credential_ref=f"credential-{connection_id}",
                    )
                    catalog.add_group_connection(group_id, connection_id)
                for profile_id in profile_ids:
                    catalog.add_profile_group(profile_id, group_id)
                    route = resolve_route(
                        "tenant:1", profile_id, group_id, "send", catalog=catalog
                    )
                    assert route.connection_id in set(connection_ids)
                    expected[profile_id] = (group_id, route.connection_id)
                    service.materialize_day(
                        "tenant:1",
                        profile_id,
                        "2026-09-20",
                        sampled_limit=1,
                        role="active",
                        quiet_limit=1,
                        work_group_id=group_id,
                        library_items=(
                            LibraryItem(
                                f"item-{profile_id}",
                                f"text-{profile_id}",
                                "version-v1",
                            ),
                        ),
                        rng=random.Random(profile_id),
                    )

            assignments = tuple((profile_id, group_id) for profile_id, (group_id, _route) in expected.items())
            for _ in expected:
                operation = service.claim_next_slot(
                    "tenant:1",
                    datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc),
                    eligible_assignments=assignments,
                )
                assert not isinstance(operation, WaitDecision)
                group_id, _route = expected[operation.profile_id]
                assert operation.work_group_id == group_id
                service.mark_slot_accepted(operation.slot_id)
            assert connection.execute(
                "SELECT COUNT(*) FROM profile_route_assignments"
            ).fetchone()[0] == len(expected)
        finally:
            connection.close()

    run_topology(((10, range(1, 51), range(1, 51)),))
    run_topology(
        (
            (20, range(101, 131), range(201, 206)),
            (21, range(131, 161), range(206, 211)),
        )
    )
    import main

    assert main._pool_size() == 1


def test_empty_library_keeps_sampled_target_and_waits_without_slots() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    service = DailyPlanService(DailyPlanRepository(connection))
    try:
        plan = service.materialize_day(
            "tenant:1", 1, "2026-09-20", sampled_limit=5, role="active", quiet_limit=1,
            work_group_id=10, library_items=(), rng=random.Random(1),
        )
        decision = service.claim_next_slot(
            "tenant:1", datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
        )
        assert plan.target == 5
        assert plan.slots == ()
        assert isinstance(decision, WaitDecision)
    finally:
        connection.close()


def test_revoked_consent_cancels_queued_slots_without_claiming_or_sending() -> None:
    from app.campaign_worker import _cancel_daily_slots_for_revoked_scopes

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    service = DailyPlanService(DailyPlanRepository(connection))
    try:
        service.materialize_day(
            "tenant:1",
            1,
            "2026-09-20",
            sampled_limit=1,
            role="active",
            quiet_limit=1,
            work_group_id=10,
            library_items=(LibraryItem("a", "account-a", "v1"),),
            rng=random.Random(1),
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS profile_automation_scope ("
            "profile_id INTEGER PRIMARY KEY, automation_group_id INTEGER, "
            "consent_state TEXT NOT NULL, revision INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO profile_automation_scope "
            "(profile_id, automation_group_id, consent_state, revision) "
            "VALUES (1, 10, 'revoked', 2)"
        )

        assert _cancel_daily_slots_for_revoked_scopes(connection, "tenant:1") == 1
        row = connection.execute(
            "SELECT status, failure_reason FROM profile_message_slots"
        ).fetchone()
        assert tuple(row) == ("cancelled", "CONSENT_REVOKED")
        decision = service.claim_next_slot(
            "tenant:1", datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc),
            eligible_assignments=((1, 10),),
        )
        assert isinstance(decision, WaitDecision)
    finally:
        connection.close()
