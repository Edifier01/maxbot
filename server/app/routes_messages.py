"""Panel API — messages."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from app.runtime import main as m

router = APIRouter(tags=["messages"])


@router.get("/api/messages")
async def get_messages():

    msgs = m.load_message_pool()
    meta = {}
    msg_file = m._messages_file()
    if msg_file.exists():
        meta["file"] = "active.txt"
        meta["size"] = msg_file.stat().st_size
    with m._conn() as c:
        row = c.execute("SELECT loaded_at FROM message_pool LIMIT 1").fetchone()
        if row:
            meta["loaded_at"] = row["loaded_at"]
    return {"count": len(msgs), "messages": msgs, "meta": meta}


@router.post("/api/messages/upload")
async def upload_messages(file: UploadFile = File(...)):

    content = await file.read(m.MAX_UPLOAD_BYTES + 1)
    if len(content) > m.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Файл слишком большой (максимум 5 МБ)")
    try:
        n = m.save_messages_file(content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    m.append_log(f"Загружено {n} сообщений")
    return {"count": n}


