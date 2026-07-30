"""Vault API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class VaultPasswordIn(BaseModel):
    password: str


router = APIRouter(tags=["vault"])


@router.get("/api/vault/status")
async def api_vault_status():
    import main as m

    return m.vault_status()


@router.post("/api/vault/setup")
async def api_vault_setup(body: VaultPasswordIn):
    import main as m

    try:
        return m.setup_vault(body.password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/api/vault/unlock")
async def api_vault_unlock(body: VaultPasswordIn):
    import main as m

    try:
        m.unlock_vault(body.password)
    except ValueError as e:
        raise HTTPException(401, str(e)) from e
    return {"ok": True, **m.vault_status()}


@router.post("/api/vault/lock")
async def api_vault_lock():
    import main as m

    st = m.vault_status()
    if st["legacy"]:
        raise HTTPException(
            400,
            "Старый ключ нельзя заблокировать — сначала защитите хранилище паролем",
        )
    if not st["protected"]:
        raise HTTPException(400, "Хранилище ещё не защищено")
    m.lock_vault()
    return {"ok": True, **m.vault_status()}
