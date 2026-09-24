"""T15: immutable reusable message-library versions."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone

import pytest

from app.repositories.message_sets import MessageSetRepository
from app.services.messages import (
    DraftValidationResult,
    MessageLibrary,
    MessageValidationError,
)


def _library() -> tuple[sqlite3.Connection, MessageLibrary]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    return connection, MessageLibrary(MessageSetRepository(connection))


def test_bom_comments_and_literal_json_are_preserved_in_published_version() -> None:
    connection, library = _library()
    try:
        result = library.preview_draft("\ufeff# note\nHello {literal}\n {\"x\": 1} \n\n")
        assert isinstance(result, DraftValidationResult)
        assert result.items == ("Hello {literal}", '{"x": 1}')
        version = library.publish_draft("tenant:1", result)
        assert library.immutable_items("tenant:1", version.version_id) == result.items
    finally:
        connection.close()


def test_txt_preserves_quoted_separators_unicode_and_duplicate_items() -> None:
    connection, library = _library()
    try:
        result = library.preview_draft(
            '\ufeff"a,b" — привет\n{"value":"a|b"}\n"a,b" — привет\n'
        )
        assert result.items == (
            '"a,b" — привет',
            '{"value":"a|b"}',
            '"a,b" — привет',
        )
        assert result.warnings == ("duplicate_texts_are_allowed",)
    finally:
        connection.close()


def test_message_preview_has_finite_byte_and_row_limits() -> None:
    connection, library = _library()
    try:
        with pytest.raises(MessageValidationError, match="too large"):
            library.preview_draft("x" * (MessageLibrary.MAX_BYTES + 1))
        with pytest.raises(MessageValidationError, match="too many items"):
            library.preview_draft("x\n" * (MessageLibrary.MAX_ITEMS + 1))
    finally:
        connection.close()


def test_publishing_v2_does_not_mutate_v1_or_consume_library_items() -> None:
    connection, library = _library()
    try:
        v1 = library.publish_draft("tenant:1", library.preview_draft("one\ntwo"))
        v2 = library.publish_draft("tenant:1", library.preview_draft("three"))

        assert library.get_version("tenant:1", v1.version_id).items == ("one", "two")
        assert library.get_version("tenant:1", v2.version_id).items == ("three",)
        assert library.current("tenant:1").version_id == v2.version_id
        assert library.summary("tenant:1", day_selection_count=10) == {
            "library_count": 1,
            "day_selection_count": 10,
            "version_id": v2.version_id,
            "checksum": v2.checksum,
        }
    finally:
        connection.close()


def test_same_version_can_be_reused_by_multiple_accounts_without_deletion() -> None:
    connection, library = _library()
    try:
        version = library.publish_draft("tenant:1", library.preview_draft("a\nb\nc"))
        assert library.immutable_items("tenant:1", version.version_id) == ("a", "b", "c")
        assert library.immutable_items("tenant:1", version.version_id) == ("a", "b", "c")
        assert connection.execute("SELECT COUNT(*) FROM message_set_items").fetchone()[0] == 3
    finally:
        connection.close()


def test_current_endpoint_keeps_five_items_after_two_complete_account_passes(
    monkeypatch,
) -> None:
    from app.repositories.daily_plans import DailyPlanRepository
    from app.routes_message_sets import get_current_message_set
    from app.services.daily_plans import DailyPlanService, LibraryItem

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        repository = MessageSetRepository(connection)
        version_id, checksum = repository.publish(
            "local", ("one", "two", "three", "four", "five")
        )
        items = tuple(
            LibraryItem(str(row["item_id"]), str(row["text"]), version_id)
            for row in repository.items("local", version_id)
        )
        service = DailyPlanService(DailyPlanRepository(connection))
        for profile_id, group_id in ((7, 3), (8, 4)):
            service.materialize_day(
                "local",
                profile_id,
                "2026-09-20",
                sampled_limit=5,
                role="active",
                quiet_limit=1,
                work_group_id=group_id,
                library_items=items,
            )
        for _ in range(10):
            claimed = service.claim_next_slot(
                "local", datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
            )
            service.mark_slot_accepted(claimed.slot_id)

        from app.routes_message_sets import m as routes_runtime

        monkeypatch.setattr(routes_runtime, "_is_server_mode", lambda: False)
        monkeypatch.setattr(routes_runtime, "_conn", lambda: connection)
        current = asyncio.run(get_current_message_set())

        assert current["version_id"] == version_id
        assert current["checksum"] == checksum
        assert current["library_count"] == 5
        assert [item["text"] for item in current["items"]] == [
            "one",
            "two",
            "three",
            "four",
            "five",
        ]
        assert connection.execute(
            "SELECT COUNT(*) FROM message_set_items WHERE scope='local' AND version_id=?",
            (version_id,),
        ).fetchone()[0] == 5
    finally:
        connection.close()


def test_current_endpoint_fails_closed_on_item_mutation(monkeypatch) -> None:
    from app.routes_message_sets import get_current_message_set
    from app.runtime import main as routes_runtime
    from fastapi import HTTPException

    connection, library = _library()
    try:
        version = library.publish_draft("local", library.preview_draft("one\ntwo"))
        connection.execute(
            "UPDATE message_set_items SET text='tampered' "
            "WHERE scope='local' AND version_id=? AND ordinal=0",
            (version.version_id,),
        )
        monkeypatch.setattr(routes_runtime, "_is_server_mode", lambda: False)
        monkeypatch.setattr(routes_runtime, "_conn", lambda: connection)
        with pytest.raises(HTTPException) as error:
            asyncio.run(get_current_message_set())
        assert error.value.status_code == 409
        assert "integrity" in str(error.value.detail)
    finally:
        connection.close()


def test_empty_or_oversized_draft_is_rejected_without_network_or_write() -> None:
    connection, library = _library()
    try:
        with pytest.raises(MessageValidationError):
            library.preview_draft("# only comments\n\n")
        with pytest.raises(MessageValidationError):
            library.preview_draft("x\n" * (MessageLibrary.MAX_ITEMS + 1))
        assert connection.execute("SELECT COUNT(*) FROM message_set_versions").fetchone()[0] == 0
    finally:
        connection.close()


def test_version_conflict_is_explicit_and_current_remains_readable() -> None:
    connection, library = _library()
    try:
        with pytest.raises(MessageValidationError):
            library.get_version("tenant:1", "missing-version")
        with pytest.raises(MessageValidationError):
            library.current("tenant:1")
    finally:
        connection.close()
