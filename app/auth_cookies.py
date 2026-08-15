"""HttpOnly auth cookie helpers (user JWT + admin impersonation backup)."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

from app.config import JWT_EXPIRE_HOURS

AUTH_COOKIE_NAME = "max_token"
ADMIN_BACKUP_COOKIE_NAME = "max_admin_token"


def _is_secure_request(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return proto == "https"


def _cookie_kwargs(request: Request, *, key: str = AUTH_COOKIE_NAME) -> dict:
    return {
        "key": key,
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
    """Set HttpOnly max_token. Persistent Max-Age only when remember_me is true."""
    kwargs = _cookie_kwargs(request)
    if remember_me:
        kwargs["max_age"] = JWT_EXPIRE_HOURS * 3600
    response.set_cookie(value=token, **kwargs)


def set_admin_backup_cookie(response: Response, token: str, request: Request) -> None:
    """Session HttpOnly backup of the admin JWT during impersonation."""
    response.set_cookie(value=token, **_cookie_kwargs(request, key=ADMIN_BACKUP_COOKIE_NAME))


def clear_auth_cookie(response: Response, request: Request) -> None:
    """Remove max_token auth cookie."""
    response.delete_cookie(**_cookie_kwargs(request))


def clear_admin_backup_cookie(response: Response, request: Request) -> None:
    """Remove max_admin_token backup cookie."""
    response.delete_cookie(**_cookie_kwargs(request, key=ADMIN_BACKUP_COOKIE_NAME))
