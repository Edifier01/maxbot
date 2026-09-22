"""T11: one automation destination, consent and destination revisions."""

from __future__ import annotations

import sqlite3

import pytest


def _repo():
    from app.repositories.automation_scope import AutomationScopeRepository

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE groups (
            id INTEGER PRIMARY KEY,
            invite_link TEXT NOT NULL,
            max_chat_id TEXT DEFAULT ''
        );
        CREATE TABLE group_profiles (group_id INTEGER, profile_id INTEGER, is_enabled INTEGER DEFAULT 1);
        INSERT INTO groups(id, invite_link, max_chat_id) VALUES (10, 'https://max.example/a', 'chat-a');
        INSERT INTO groups(id, invite_link, max_chat_id) VALUES (20, 'https://max.example/b', 'chat-b');
        INSERT INTO group_profiles(group_id, profile_id) VALUES (10, 7);
        INSERT INTO group_profiles(group_id, profile_id) VALUES (20, 7);
        """
    )
    repo = AutomationScopeRepository(conn)
    repo.ensure_schema()
    return conn, repo


def test_multiple_legacy_groups_require_explicit_selection() -> None:
    from app.repositories.automation_scope import AutomationScopeError

    _conn, repo = _repo()
    manifest = repo.migration_manifest(7)
    assert manifest.status == "BLOCKED"
    assert manifest.code == "WORK_GROUP_SELECTION_REQUIRED"
    with pytest.raises(AutomationScopeError) as caught:
        repo.migrate_legacy_scope(7)
    assert caught.value.code == "WORK_GROUP_SELECTION_REQUIRED"
    assert repo.legacy_group_ids(7) == [10, 20]


def test_destination_revision_and_consent_gate_external_action() -> None:
    from app.repositories.automation_scope import AutomationScopeError

    _conn, repo = _repo()
    repo.select_work_group(7, 10)
    snapshot = repo.destination_snapshot(10)
    assert snapshot["max_chat_id"] == "chat-a"
    repo.update_destination(10, "https://max.example/new")
    assert repo.destination_snapshot(10)["max_chat_id"] == ""
    with pytest.raises(AutomationScopeError) as caught:
        repo.require_external_action(7, 10, snapshot["destination_revision"])
    assert caught.value.code == "DESTINATION_REVIEW_REQUIRED"

    repo.verify_destination(10, "chat-new")
    assert repo.require_external_action(7, 10, repo.destination_snapshot(10)["destination_revision"])["chat_id"] == "chat-new"
    repo.revoke_consent(7)
    with pytest.raises(AutomationScopeError) as consent:
        repo.require_external_action(7, 10, repo.destination_snapshot(10)["destination_revision"])
    assert consent.value.code == "CONSENT_REVOKED"


def test_unlink_preserves_legacy_association_and_does_not_reset_budget() -> None:
    _conn, repo = _repo()
    repo.select_work_group(7, 10)
    repo.unlink_work_group(7)
    assert repo.legacy_group_ids(7) == [10, 20]
    assert repo.scope_for(7)["automation_group_id"] is None
