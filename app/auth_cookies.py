"""HttpOnly auth cookie helpers for persistent login (remember me)."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

from app.config import JWT_EXPIRE_HOURS

AUTH_COOKIE_NAME = "max_token"


def _is_secure_request(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return proto == "https"


def _cookie_kwargs(request: Request) -> dict:
    return {
        "key": AUTH_COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": _is_secure_request(request),
    }


def set_auth_cookie(
    response: Response,
    token: str,
    remember_me: bool,
    request: Request,
) -> None:
    """Set persistent max_token cookie when remember_me is true."""
    if not remember_me:
        return
    response.set_cookie(
        value=token,
        max_age=JWT_EXPIRE_HOURS * 3600,
        **_cookie_kwargs(request),
    )


def clear_auth_cookie(response: Response, request: Request) -> None:
    """Remove max_token auth cookie."""
    response.delete_cookie(**_cookie_kwargs(request))
