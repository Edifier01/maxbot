"""Static panel pages."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["pages"])


def _static():
    import main as m

    return m.STATIC


@router.get("/")
async def index():
    import main as m

    return FileResponse(_static() / "index.html")


@router.get("/auth.html")
async def auth_page():
    import main as m

    return FileResponse(_static() / "auth.html")


@router.get("/admin.html")
async def admin_page():
    import main as m

    return FileResponse(_static() / "admin.html")
