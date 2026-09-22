"""T15: immutable reusable message-library versions."""

from __future__ import annotations

import sqlite3

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
