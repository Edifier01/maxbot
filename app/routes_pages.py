"""Static panel pages."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse
from app.runtime import main as m

router = APIRouter(tags=["pages"])


def _static():

    return m.STATIC


@router.get("/")
async def index():

    return FileResponse(_static() / "index.html")


@router.get("/auth.html")
async def auth_page():

    return FileResponse(_static() / "auth.html")


@router.get("/admin.html")
async def admin_page():

    return FileResponse(_static() / "admin.html")
