"""Read-only scoped views of immutable message-library versions."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.runtime import main as m
from app.services.messages import MessageLibrary, MessageValidationError


router = APIRouter(tags=["message-sets"])


class MessagePreviewIn(BaseModel):
    raw: str


@router.post("/api/message-sets/preview")
async def preview_message_set(body: MessagePreviewIn):
    """Validate a draft without creating a version, database row, or plan."""
    try:
        result = MessageLibrary().preview_draft(body.raw)
    except MessageValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "valid": result.valid,
        "items": list(result.items),
        "count": len(result.items),
        "errors": list(result.errors),
        "warnings": list(result.warnings),
    }


def _scope() -> str:
    if m._is_server_mode():
        from app.tenant import get_tenant_id, use_global_data

        if use_global_data() or get_tenant_id() is None:
            return "global"
        return f"tenant:{get_tenant_id()}"
    return "local"


def _read_version(connection, scope: str, version_id: str | None = None):
    if version_id is None:
        row = connection.execute(
            "SELECT * FROM message_set_versions WHERE scope=? AND is_current=1 "
            "ORDER BY created_at DESC LIMIT 1",
            (scope,),
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT * FROM message_set_versions WHERE scope=? AND version_id=?",
            (scope, version_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "message version is unavailable")
    items = connection.execute(
        "SELECT item_id, text FROM message_set_items WHERE scope=? AND version_id=? "
        "ORDER BY ordinal",
        (scope, row["version_id"]),
    ).fetchall()
    return {
        "scope": scope,
        "version_id": row["version_id"],
        "checksum": row["checksum"],
        "library_count": int(row["item_count"]),
        "items": [dict(item) for item in items],
    }


@router.get("/api/message-sets/current")
async def get_current_message_set():
    with m._conn() as connection:
        return _read_version(connection, _scope())


@router.get("/api/message-sets/{version_id}")
async def get_message_set(version_id: str):
    with m._conn() as connection:
        return _read_version(connection, _scope(), version_id)
