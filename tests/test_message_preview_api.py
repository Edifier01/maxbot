"""T25 draft preview is read-only and uses the immutable library validator."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest
from fastapi import HTTPException


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    return connection


def test_preview_does_not_publish_or_call_external_runtime(monkeypatch) -> None:
    from app.routes_message_sets import MessagePreviewIn, preview_message_set
    from app.runtime import main as runtime

    connection = _connection()
    monkeypatch.setattr(runtime, "_is_server_mode", lambda: False)
    monkeypatch.setattr(runtime, "_conn", lambda: connection)
    result = asyncio.run(
        preview_message_set(
            MessagePreviewIn(raw="# comment\nHello {name}\n\nHello {name}\n")
        )
    )

    assert result["valid"] is True
    assert result["items"] == ["Hello {name}", "Hello {name}"]
    assert result["warnings"] == ["duplicate_texts_are_allowed"]
    assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []


def test_preview_rejects_empty_draft_without_writing(monkeypatch) -> None:
    from app.routes_message_sets import MessagePreviewIn, preview_message_set
    from app.runtime import main as runtime

    connection = _connection()
    monkeypatch.setattr(runtime, "_is_server_mode", lambda: False)
    monkeypatch.setattr(runtime, "_conn", lambda: connection)
    with pytest.raises(HTTPException) as error:
        asyncio.run(preview_message_set(MessagePreviewIn(raw="# only comment\n")))
    assert error.value.status_code == 400
    assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
