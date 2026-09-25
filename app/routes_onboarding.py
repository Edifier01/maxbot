"""Owner invite management and isolated public onboarding entry points."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import asyncio
import logging
import os
import re
import secrets
import shutil
import sqlite3
from urllib.parse import urlsplit
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from app import db_pg, vault
from app.config import JWT_SECRET, is_server_mode
from app.repositories.onboarding import (
    OnboardingRepository,
    normalize_full_name,
    token_hash,
)
from app.runtime import main as m
from app.tenant import get_tenant_id, get_user_id
from app.tenant_sqlite import tenant_conn

router = APIRouter(tags=["onboarding"])
_COOKIE = "max_onboarding"
_SESSION_TTL = timedelta(minutes=45)
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,100}$")
_AUTH_RUNTIME: dict[str, dict] = {}
_AUTH_TASKS: dict[str, asyncio.Task] = {}
_ONBOARDING_LOCKS: dict[str, asyncio.Lock] = {}
_LOG = logging.getLogger(__name__)


def _onboarding_lock(session_id: str) -> asyncio.Lock:
    return _ONBOARDING_LOCKS.setdefault(str(session_id), asyncio.Lock())


class InviteCreateIn(BaseModel):
    expires_days: int = Field(default=7, ge=1, le=30)
    max_uses: int | None = Field(default=None, ge=1, le=10000)


class OnboardingStartIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=240)
    phone: str = Field(min_length=5, max_length=64)
    consent: bool


class OnboardingCodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class OnboardingPasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class OnboardingNameIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=180)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _public_base_url() -> str:
    raw = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise HTTPException(503, "PUBLIC_BASE_URL_NOT_CONFIGURED") from exc
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username
        or parsed.password or parsed.query or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise HTTPException(503, "PUBLIC_BASE_URL_NOT_CONFIGURED")
    return raw


def _cookie_payload(tenant_id: int, session_id: str, secret: str) -> str:
    body = f"v1.{int(tenant_id)}.{session_id}.{secret}"
    signature = hmac.new(JWT_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def _cookie_session(request: Request) -> tuple[int, str, str]:
    raw = request.cookies.get(_COOKIE, "")
    parts = raw.split(".")
    if len(parts) != 5 or parts[0] != "v1" or not parts[1].isdigit():
        raise HTTPException(401, "ONBOARDING_SESSION_REQUIRED")
    body = ".".join(parts[:4])
    expected = hmac.new(JWT_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(parts[4], expected):
        raise HTTPException(401, "ONBOARDING_SESSION_INVALID")
    return int(parts[1]), parts[2], parts[3]


def _session_repo(request: Request):
    tenant_id, session_id, secret = _cookie_session(request)
    with tenant_conn(tenant_id) as conn:
        repo = OnboardingRepository(conn)
        row = repo.get_session(session_id)
        if row is None or not hmac.compare_digest(
            str(row["session_token_hash"]), token_hash(secret)
        ):
            raise HTTPException(401, "ONBOARDING_SESSION_INVALID")
        if str(row["state"]) != "completed" and not _invite_valid(row, _now()):
            raise HTTPException(410, "INVITE_UNAVAILABLE")
        if str(row["expires_at"]) <= _iso(_now()):
            raise HTTPException(410, "ONBOARDING_SESSION_EXPIRED")
        return tenant_id, row


def _invite_valid(row, now: datetime) -> bool:
    try:
        expiry_key = "invite_expires_at" if "invite_expires_at" in row.keys() else "expires_at"
        active_key = "invite_active" if "invite_active" in row.keys() else "is_active"
        expires = datetime.fromisoformat(str(row[expiry_key]).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return bool(
        int(row[active_key] or 0)
        and int(row["group_is_active"] or 0)
        and int(row["destination_verified"] or 0)
        and str(row["max_chat_id"] or "").strip()
        and expires > now
        and (row["max_uses"] is None or int(row["uses_count"]) < int(row["max_uses"]))
    )


def _csrf(request: Request, secret: str) -> None:
    origin = request.headers.get("origin", "").strip()
    host = request.headers.get("host", "").strip()
    if not origin or not host:
        raise HTTPException(403, "ONBOARDING_ORIGIN_REQUIRED")
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or parsed.netloc.casefold() != host.casefold() or parsed.path not in {"", "/"}:
        raise HTTPException(403, "ONBOARDING_ORIGIN_INVALID")
    expected = hmac.new(secret.encode(), b"csrf", hashlib.sha256).hexdigest()
    if not hmac.compare_digest(request.headers.get("x-onboarding-csrf", ""), expected):
        raise HTTPException(403, "ONBOARDING_CSRF_INVALID")


def _private(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _require_server() -> None:
    if not is_server_mode():
        raise HTTPException(404, "Not found")


def _active_owner_invite(group_id: int):
    with m._conn() as conn:
        group = conn.execute(
            "SELECT id, is_active, destination_verified, max_chat_id FROM groups WHERE id=?",
            (int(group_id),),
        ).fetchone()
        if group is None:
            raise HTTPException(404, "Группа не найдена")
        if not int(group["is_active"] or 0):
            raise HTTPException(409, "GROUP_INACTIVE")
        if not int(group["destination_verified"] or 0) or not str(group["max_chat_id"] or "").strip():
            raise HTTPException(409, "DESTINATION_REVIEW_REQUIRED")
        repo = OnboardingRepository(conn)
        row = repo.get_active_invite(group_id)
        if row is None:
            return None
        return dict(row)


@router.get("/api/groups/{group_id}/onboarding-invite")
async def get_onboarding_invite(group_id: int):
    _require_server()
    current = _active_owner_invite(group_id)
    if current is None:
        return {"active": False}
    try:
        token = vault.get_fernet(m._resolve_data_dir()).decrypt(
            str(current["token_ciphertext"]).encode()
        ).decode("ascii")
    except Exception as exc:
        raise HTTPException(503, "INVITE_SECRET_UNAVAILABLE") from exc
    return {
        "active": _invite_valid_owner(current, _now()),
        "url": f"{_public_base_url()}/join/{token}",
        "created_at": current["created_at"],
        "expires_at": current["expires_at"],
        "max_uses": current["max_uses"],
        "uses_count": current["uses_count"],
    }


def _invite_valid_owner(row, now: datetime) -> bool:
    expiry = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
    return bool(row["is_active"] and expiry > now and (row["max_uses"] is None or row["uses_count"] < row["max_uses"]))


@router.post("/api/groups/{group_id}/onboarding-invite")
async def create_onboarding_invite(group_id: int, body: InviteCreateIn):
    _require_server()
    tenant_id = get_tenant_id()
    if tenant_id is None:
        raise HTTPException(403, "TENANT_REQUIRED")
    base_url = _public_base_url()
    token = secrets.token_urlsafe(32)
    digest = token_hash(token)
    created = _now()
    expiry = created + timedelta(days=body.expires_days)
    try:
        encrypted = vault.get_fernet(m._resolve_data_dir()).encrypt(token.encode()).decode("ascii")
    except Exception as exc:
        raise HTTPException(503, "VAULT_UNAVAILABLE") from exc
    with m._conn() as conn:
        repo = OnboardingRepository(conn)
        old = repo.get_active_invite(group_id)
        old_hash = str(old["token_hash"]) if old else None
        try:
            repo.create_invite(
                group_id, digest, encrypted, _iso(created), _iso(expiry),
                body.max_uses, created_by=get_user_id(),
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    if old_hash:
        db_pg.delete_onboarding_invite_locator(old_hash)
    try:
        db_pg.register_onboarding_invite(digest, tenant_id, expiry)
    except Exception as exc:
        with m._conn() as conn:
            OnboardingRepository(conn).revoke_invite(group_id, _iso(_now()))
        raise HTTPException(503, "INVITE_LOCATOR_UNAVAILABLE") from exc
    return {
        "active": True,
        "url": f"{base_url}/join/{token}",
        "created_at": _iso(created),
        "expires_at": _iso(expiry),
        "max_uses": body.max_uses,
        "uses_count": 0,
    }


@router.delete("/api/groups/{group_id}/onboarding-invite")
async def delete_onboarding_invite(group_id: int):
    _require_server()
    with m._conn() as conn:
        repo = OnboardingRepository(conn)
        current = repo.get_active_invite(group_id)
        revoked = repo.revoke_invite(group_id, _iso(_now()))
    if current is not None:
        db_pg.delete_onboarding_invite_locator(str(current["token_hash"]))
    return {"ok": True, "revoked": revoked}


@router.get("/join/{token}")
async def consume_invite(token: str, request: Request):
    _require_server()
    if not _TOKEN_RE.fullmatch(token):
        raise HTTPException(404, "Ссылка недействительна или истекла")
    from app import auth_rate_limit

    ip = auth_rate_limit.client_ip(request)
    allowed = await asyncio.to_thread(
        auth_rate_limit.check_auth_rate_limit,
        f"onboarding_exchange_ip:{ip}", 20, 3600,
    )
    if not allowed:
        raise HTTPException(429, "ONBOARDING_RATE_LIMITED")
    digest = token_hash(token)
    tenant_id = db_pg.get_onboarding_invite_tenant(digest)
    if tenant_id is None:
        raise HTTPException(404, "Ссылка недействительна или истекла")
    now = _now()
    session_id = secrets.token_hex(16)
    secret = secrets.token_urlsafe(32)
    with tenant_conn(tenant_id) as conn:
        repo = OnboardingRepository(conn)
        invite = repo.get_invite_by_hash(digest)
        if invite is None or not _invite_valid(invite, now):
            raise HTTPException(404, "Ссылка недействительна или истекла")
        session_expiry = min(now + _SESSION_TTL, datetime.fromisoformat(str(invite["expires_at"]).replace("Z", "+00:00")))
        repo.create_session(session_id, token_hash(secret), int(invite["id"]), _iso(now), _iso(session_expiry))
    response = RedirectResponse("/join", status_code=303)
    response.set_cookie(
        _COOKIE, _cookie_payload(tenant_id, session_id, secret),
        max_age=max(1, int((session_expiry - now).total_seconds())),
        httponly=True, secure=True, samesite="lax", path="/",
    )
    return _private(response)


@router.get("/join")
async def join_page():
    _require_server()
    page = (m.STATIC / "join.html").read_text(encoding="utf-8")
    script_path = m.STATIC / "js" / "join.js"
    script_version = hashlib.sha256(script_path.read_bytes()).hexdigest()[:12]
    page = page.replace(
        'src="/static/js/join.js"',
        f'src="/static/js/join.js?v={script_version}"',
    )
    response = HTMLResponse(page)
    return _private(response)


@router.get("/api/public/onboarding/status")
async def onboarding_status(request: Request):
    _require_server()
    tenant_id, row = _session_repo(request)
    existing_name = ""
    if row["name_confirmation_required"] and str(row["state"]) in {"waiting_membership", "finalizing"} and row["phone"]:
        with tenant_conn(tenant_id) as conn:
            profile = conn.execute("SELECT full_name FROM profiles WHERE phone=?", (str(row["phone"]),)).fetchone()
            existing_name = str(profile["full_name"] or "") if profile else ""
    response = {
        "state": str(row["state"]),
        "group_name": str(row["group_name"]),
        "invite_link": str(row["invite_link"] or ""),
        "full_name": str(row["full_name"] or ""),
        "phone": str(row["phone"] or ""),
        "name_confirmation_required": bool(row["name_confirmation_required"]) and str(row["state"]) in {"waiting_membership", "finalizing"},
        "existing_name": existing_name,
        "last_error_code": str(row["last_error_code"] or ""),
        "hint": str((_AUTH_RUNTIME.get(row["id"]) or {}).get("hint", "")),
        "expires_at": str(row["expires_at"]),
        "csrf_token": hmac.new(_cookie_session(request)[2].encode(), b"csrf", hashlib.sha256).hexdigest(),
    }
    return _private(Response(content=__import__("json").dumps(response, ensure_ascii=False), media_type="application/json"))


@router.post("/api/public/onboarding/start")
async def onboarding_start(body: OnboardingStartIn, request: Request):
    _require_server()
    tenant_id, session_id, secret = _cookie_session(request)
    _csrf(request, secret)
    if not body.consent:
        raise HTTPException(400, "CONSENT_REQUIRED")
    try:
        full_name = normalize_full_name(body.full_name)
        phone = m._normalize_phone(body.phone)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    from app import auth_rate_limit

    ip = auth_rate_limit.client_ip(request)
    phone_key = hmac.new(JWT_SECRET.encode(), phone.encode(), hashlib.sha256).hexdigest()
    ip_allowed, phone_allowed = await asyncio.gather(
        asyncio.to_thread(auth_rate_limit.check_auth_rate_limit, f"onboarding_ip:{ip}", 20, 3600),
        asyncio.to_thread(auth_rate_limit.check_auth_rate_limit, f"onboarding_phone:{phone_key}", 3, 3600),
    )
    if not ip_allowed or not phone_allowed:
        raise HTTPException(429, "ONBOARDING_RATE_LIMITED")
    existing_name = ""
    with tenant_conn(tenant_id) as conn:
        repo = OnboardingRepository(conn)
        row = repo.get_session(session_id)
        if row is None or not _invite_valid(row, _now()):
            raise HTTPException(410, "INVITE_UNAVAILABLE")
        existing = conn.execute("SELECT id, full_name, status FROM profiles WHERE phone=?", (phone,)).fetchone()
        existing_name = str(existing["full_name"] or "") if existing else ""
        repo.update_session(
            session_id, phone=phone, full_name=full_name, consent_at=_iso(_now()),
            state="ready_to_auth", name_confirmation_required=bool(existing and existing["full_name"]),
            updated_at=_iso(_now()),
        )
    runtime = _AUTH_RUNTIME.setdefault(session_id, {"tenant_id": tenant_id, "codes": asyncio.Queue(), "passwords": asyncio.Queue(), "state": "requesting_code", "hint": ""})
    runtime.update(tenant_id=tenant_id, state="requesting_code", hint="")
    _persist_state(tenant_id, session_id, "requesting_code")
    _launch_auth(tenant_id, session_id, phone)
    return {
        "ok": True,
        "state": "requesting_code",
        "phone_masked": _mask_phone(phone),
    }


@router.post("/api/public/onboarding/code")
async def onboarding_code(body: OnboardingCodeIn, request: Request):
    _require_server()
    tenant_id, session_id, secret = _cookie_session(request)
    _csrf(request, secret)
    live_tenant, live_row = _session_repo(request)
    if live_tenant != tenant_id or str(live_row["id"]) != session_id:
        raise HTTPException(401, "ONBOARDING_SESSION_INVALID")
    async with _onboarding_lock(session_id):
        runtime = _AUTH_RUNTIME.get(session_id)
        if runtime is None or runtime.get("state") != "waiting_code":
            raise HTTPException(409, "ONBOARDING_CODE_NOT_EXPECTED")
        if not body.code.isascii() or not body.code.isdigit():
            raise HTTPException(400, "OTP_FORMAT_INVALID")
        if runtime["codes"].qsize():
            raise HTTPException(409, "ONBOARDING_CODE_ALREADY_QUEUED")
        await runtime["codes"].put(body.code)
        runtime["state"] = "verifying_code"
        _persist_state(tenant_id, session_id, "verifying_code")
    return {"ok": True, "state": "verifying_code"}


@router.post("/api/public/onboarding/password")
async def onboarding_password(body: OnboardingPasswordIn, request: Request):
    _require_server()
    tenant_id, session_id, secret = _cookie_session(request)
    _csrf(request, secret)
    live_tenant, live_row = _session_repo(request)
    if live_tenant != tenant_id or str(live_row["id"]) != session_id:
        raise HTTPException(401, "ONBOARDING_SESSION_INVALID")
    async with _onboarding_lock(session_id):
        runtime = _AUTH_RUNTIME.get(session_id)
        if runtime is None or runtime.get("state") != "waiting_password":
            raise HTTPException(409, "ONBOARDING_PASSWORD_NOT_EXPECTED")
        if runtime["passwords"].qsize():
            raise HTTPException(409, "ONBOARDING_PASSWORD_ALREADY_QUEUED")
        await runtime["passwords"].put(body.password)
        runtime["state"] = "verifying_password"
        _persist_state(tenant_id, session_id, "verifying_password")
    return {"ok": True, "state": "verifying_password"}


@router.post("/api/public/onboarding/resend-code")
async def onboarding_resend_code(request: Request):
    _require_server()
    tenant_id, session_id, secret = _cookie_session(request)
    _csrf(request, secret)
    live_tenant, live_row = _session_repo(request)
    if live_tenant != tenant_id or str(live_row["id"]) != session_id:
        raise HTTPException(401, "ONBOARDING_SESSION_INVALID")
    from app import auth_rate_limit

    ip = auth_rate_limit.client_ip(request)
    allowed = await asyncio.to_thread(
        auth_rate_limit.check_auth_rate_limit,
        f"onboarding_resend:{ip}:{session_id}", 3, 3600,
    )
    if not allowed:
        raise HTTPException(429, "ONBOARDING_RATE_LIMITED")
    async with _onboarding_lock(session_id):
        with tenant_conn(tenant_id) as conn:
            row = OnboardingRepository(conn).get_session(session_id)
            if row is None or not _invite_valid(row, _now()):
                raise HTTPException(410, "INVITE_UNAVAILABLE")
            if not row["phone"]:
                raise HTTPException(409, "ONBOARDING_START_REQUIRED")
            phone = str(row["phone"])
        runtime = _AUTH_RUNTIME.get(session_id)
        task = _AUTH_TASKS.get(session_id)
        if task is not None and not task.done():
            raise HTTPException(409, "ONBOARDING_AUTH_RUNNING")
        if runtime is None:
            runtime = {"tenant_id": tenant_id, "codes": asyncio.Queue(), "passwords": asyncio.Queue(), "state": "requesting_code", "hint": ""}
            _AUTH_RUNTIME[session_id] = runtime
        directory = _onboarding_dir(tenant_id, session_id)
        for file in directory.glob("session.db*"):
            file.unlink(missing_ok=True)
        runtime["codes"] = asyncio.Queue()
        runtime["passwords"] = asyncio.Queue()
        runtime.update(state="requesting_code", hint="")
        _persist_state(tenant_id, session_id, "requesting_code", last_error_code=None)
        _launch_auth(tenant_id, session_id, phone)
    return {"ok": True, "state": "requesting_code"}


@router.post("/api/public/onboarding/confirm-name")
async def onboarding_confirm_name(body: OnboardingNameIn, request: Request):
    _require_server()
    tenant_id, session_id, secret = _cookie_session(request)
    _csrf(request, secret)
    live_tenant, live_row = _session_repo(request)
    if live_tenant != tenant_id or str(live_row["id"]) != session_id:
        raise HTTPException(401, "ONBOARDING_SESSION_INVALID")
    try:
        name = normalize_full_name(body.full_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    with tenant_conn(tenant_id) as conn:
        row = OnboardingRepository(conn).get_session(session_id)
        if row is None or str(row["state"]) != "waiting_membership":
            raise HTTPException(409, "ONBOARDING_AUTH_REQUIRED")
        if not row["name_confirmation_required"]:
            raise HTTPException(409, "PROFILE_NAME_CONFIRMATION_NOT_REQUIRED")
        OnboardingRepository(conn).update_session(session_id, full_name=name, name_confirmation_required=0, updated_at=_iso(_now()))
    return {"ok": True}


@router.post("/api/public/onboarding/check-membership")
async def onboarding_check_membership(request: Request):
    _require_server()
    tenant_id, session_id, secret = _cookie_session(request)
    _csrf(request, secret)
    async with _onboarding_lock(session_id):
        live_tenant, live_row = _session_repo(request)
        if live_tenant != tenant_id or str(live_row["id"]) != session_id:
            raise HTTPException(401, "ONBOARDING_SESSION_INVALID")
        with tenant_conn(tenant_id) as conn:
            row = OnboardingRepository(conn).get_session(session_id)
            if row is None or str(row["state"]) not in {"waiting_membership", "finalizing"}:
                if row is not None and str(row["state"]) == "completed":
                    return {"ok": True, "state": "completed", "joined": True}
                raise HTTPException(409, "ONBOARDING_AUTH_REQUIRED")
            if row["name_confirmation_required"]:
                raise HTTPException(409, "PROFILE_NAME_CONFIRMATION_REQUIRED")
        try:
            completed = await _check_membership_and_finalize(tenant_id, session_id, row)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(409, "ONBOARDING_FINALIZATION_FAILED") from exc
        return {"ok": True, "state": "completed" if completed else "waiting_membership", "joined": completed}


def _mask_phone(phone: str) -> str:
    return "•" * max(0, len(phone) - 4) + phone[-4:]


def _onboarding_dir(tenant_id: int, session_id: str) -> Path:
    with __import__("app.tenant", fromlist=["tenant_scope"]).tenant_scope(
        tenant_id=tenant_id, role="admin"
    ):
        path = m._resolve_data_dir() / "sessions" / "onboarding" / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _onboarding_proxy(tenant_id: int, session_id: str, phone: str) -> str:
    """Use the group's configured route throughout temporary authorization."""
    from antiban_core import parse_proxy_list
    from app.repositories.weekly_schedule import WeeklyScheduleRepository

    with tenant_conn(tenant_id) as conn:
        row = OnboardingRepository(conn).get_session(session_id)
        if row is None:
            raise RuntimeError("ONBOARDING_SESSION_INVALID")
        group_id = int(row["group_id"])
        group = conn.execute("SELECT proxy FROM groups WHERE id=?", (group_id,)).fetchone()
        proxies = parse_proxy_list(str(group["proxy"] or "") if group else "")
        if not proxies:
            raise RuntimeError("PROXY_ASSIGNMENT_REQUIRED")
        profile = conn.execute("SELECT id FROM profiles WHERE phone=?", (phone,)).fetchone()
        if profile is not None:
            schedule = WeeklyScheduleRepository(conn)
            profile_id = int(profile["id"])
            if schedule.assignment_for(profile_id, group_id) is None:
                schedule.assign_profile(profile_id, group_id)
                # A new profile authenticated through the first group route.
                # Keep that route when its permanent assignment is created.
                fingerprint = hashlib.sha256(proxies[0].strip().encode("utf-8")).hexdigest()
                conn.execute(
                    "UPDATE profile_group_proxy_assignments SET proxy_fingerprint=? "
                    "WHERE profile_id=? AND group_id=?",
                    (fingerprint, profile_id, group_id),
                )
                conn.commit()
            proxy = schedule.assigned_proxy_url(profile_id, group_id)
            if proxy:
                return proxy
            raise RuntimeError("PROXY_ASSIGNMENT_REQUIRED")
        return proxies[0]


def _persist_state(tenant_id: int, session_id: str, state: str, **fields) -> None:
    with tenant_conn(tenant_id) as conn:
        repo = OnboardingRepository(conn)
        repo.update_session(
            session_id, state=state, updated_at=_iso(_now()), **fields
        )


class _OnboardingSmsAuthFlow:
    """Ephemeral OTP/password flow; credentials live only in process queues."""
    def __init__(self, session_id: str, runtime: dict) -> None:
        self.session_id = session_id
        self.runtime = runtime

    async def authenticate(self, app):
        from pymax.auth.models import AuthResult
        from pymax.exceptions import ApiError
        from app.platform_policy import MaxAction

        phone = str(app.config.phone)
        gateway = m._max_gateway(app)
        _runtime_state(self.session_id, "requesting_code")
        gateway._require(MaxAction.REQUEST_OTP)
        start = await app.api.auth.request_code(phone)
        _runtime_state(self.session_id, "waiting_code")
        code = await asyncio.wait_for(self.runtime["codes"].get(), timeout=300)
        _runtime_state(self.session_id, "verifying_code")
        gateway._require(MaxAction.VERIFY_AUTH)
        result = await app.api.auth.send_code(start.token, code)
        token = result.login_token
        if result.password_challenge is not None:
            track_id = result.password_challenge.track_id
            for attempt in range(5):
                _runtime_state(self.session_id, "waiting_password", hint=result.password_challenge.hint or "")
                password = await asyncio.wait_for(self.runtime["passwords"].get(), timeout=300)
                _runtime_state(self.session_id, "verifying_password")
                gateway._require(MaxAction.VERIFY_AUTH)
                try:
                    response = await app.api.auth.check_password(track_id, password)
                except ApiError:
                    response = None
                if response is not None and not response.error and response.login_token:
                    token = response.login_token
                    break
                _runtime_state(self.session_id, "waiting_password", hint="Пароль не подошёл. Попробуйте ещё раз.")
            if not token:
                raise RuntimeError("MAX_CLOUD_PASSWORD_REJECTED")
        elif result.register_token:
            raise RuntimeError("MAX_ACCOUNT_REGISTRATION_REQUIRED")
        if not token:
            raise RuntimeError("MAX_AUTH_TOKEN_MISSING")
        return AuthResult(token=token)


def _runtime_state(session_id: str, state: str, *, hint: str = "") -> None:
    runtime = _AUTH_RUNTIME.get(session_id)
    if runtime is not None:
        runtime.update(state=state, hint=hint)
        _persist_state(runtime["tenant_id"], session_id, state)


def _onboarding_failure_code(exc: Exception) -> str:
    from app.platform_policy import PlatformAuthorizationHold
    from app.recovery_hold import RecoveryHoldActive

    if isinstance(exc, (PlatformAuthorizationHold, RecoveryHoldActive)):
        return "MAX_AUTH_UNAVAILABLE"
    explicit = str(exc)
    if explicit in {
        "PROXY_ASSIGNMENT_REQUIRED",
        "MAX_ACCOUNT_REGISTRATION_REQUIRED",
        "MAX_CLOUD_PASSWORD_REJECTED",
    }:
        return explicit
    return "MAX_AUTH_FAILED"


async def _run_onboarding_auth(tenant_id: int, session_id: str, phone: str) -> None:
    from app.tenant import tenant_scope

    runtime = _AUTH_RUNTIME[session_id]
    directory = _onboarding_dir(tenant_id, session_id)
    client = None
    saved_encrypted_session = False
    try:
        with tenant_scope(tenant_id=tenant_id, role="admin"):
            m._ensure_vault_unlocked()
            client = m._build_pymax_client(
                phone=phone,
                work_dir=str(directory),
                session_name="session.db",
                auth_flow=_OnboardingSmsAuthFlow(session_id, runtime),
                proxy=_onboarding_proxy(tenant_id, session_id, phone),
                identity=None,
            )
            gateway = m._max_gateway(client)
            await asyncio.wait_for(gateway.connect(), timeout=600)
            user_id = getattr(getattr(client.me, "contact", None), "id", None)
            await m._safe_stop(client)
            client = None
            if not user_id:
                raise RuntimeError("MAX_AUTH_USER_UNKNOWN")
            session_file = directory / "session.db"
            if not session_file.is_file():
                raise RuntimeError("MAX_SESSION_MISSING")
            from app.vault import get_fernet

            encrypted = get_fernet(m._resolve_data_dir()).encrypt(session_file.read_bytes())
            enc_file = directory / "session.db.enc"
            tmp_file = directory / "session.db.enc.tmp"
            tmp_file.write_bytes(encrypted)
            os.replace(tmp_file, enc_file)
            for path in (session_file, directory / "session.db-wal", directory / "session.db-shm"):
                path.unlink(missing_ok=True)
            saved_encrypted_session = True
            _persist_state(tenant_id, session_id, "waiting_membership", max_user_id=str(user_id))
            runtime.update(state="waiting_membership", max_user_id=str(user_id))
    except asyncio.CancelledError:
        _persist_state(tenant_id, session_id, "interrupted", last_error_code="AUTH_INTERRUPTED")
        raise
    except Exception as exc:
        code = _onboarding_failure_code(exc)
        _LOG.warning(
            "onboarding auth failed code=%s stage=%s exception_type=%s",
            code, runtime.get("state", "unknown"), type(exc).__name__,
        )
        runtime.update(state="failed", error_code=code)
        _persist_state(tenant_id, session_id, "failed", last_error_code=code)
    finally:
        if client is not None:
            try:
                await m._safe_stop(client)
            except Exception:
                pass
        if not saved_encrypted_session:
            for path in directory.glob("session.db*"):
                path.unlink(missing_ok=True)


def _launch_auth(tenant_id: int, session_id: str, phone: str) -> None:
    if session_id in _AUTH_TASKS and not _AUTH_TASKS[session_id].done():
        return
    runtime = _AUTH_RUNTIME.setdefault(
        session_id,
        {"tenant_id": tenant_id, "codes": asyncio.Queue(), "passwords": asyncio.Queue(), "state": "requesting_code", "hint": ""},
    )
    runtime["tenant_id"] = tenant_id
    _AUTH_TASKS[session_id] = asyncio.create_task(
        _run_onboarding_auth(tenant_id, session_id, phone)
    )


def _member_proof(chat, expected_chat_id: str) -> bool:
    try:
        chat_id = str(getattr(chat, "id", ""))
        status = getattr(chat, "status", "")
        status = str(getattr(status, "value", status)).casefold()
        joined_at = int(getattr(chat, "join_time", 0) or 0)
    except (TypeError, ValueError):
        return False
    return chat_id == str(expected_chat_id) and status in {"member", "active", "joined", "in"} and joined_at > 0


def recover_and_cleanup_onboarding() -> int:
    """Recover a half-promoted session and delete only expired onboarding data."""
    from app.tenant import tenant_scope

    data_root = m._resolve_data_root()
    tenants_root = data_root / "tenants"
    recovered = 0
    if not tenants_root.is_dir():
        return recovered
    for tenant_path in tenants_root.iterdir():
        if not tenant_path.is_dir() or not tenant_path.name.isdigit():
            continue
        tenant_id = int(tenant_path.name)
        with tenant_scope(tenant_id=tenant_id, role="admin"):
            with m._conn() as conn:
                try:
                    rows = conn.execute(
                        "SELECT id, state, expires_at, profile_id, created_profile, promotion_state "
                        "FROM onboarding_sessions"
                    ).fetchall()
                except sqlite3.OperationalError:
                    continue
                for row in rows:
                    sid = str(row["id"])
                    directory = tenant_path / "sessions" / "onboarding" / sid
                    if str(row["state"]) in {"requesting_code", "waiting_code", "verifying_code", "waiting_password", "verifying_password", "authorized"}:
                        conn.execute("UPDATE onboarding_sessions SET state='interrupted', last_error_code='AUTH_INTERRUPTED', updated_at=? WHERE id=?", (_iso(_now()), sid))
                        recovered += 1
                    if str(row["promotion_state"]) in {"promoting", "promoted"} and str(row["state"]) != "completed" and row["profile_id"]:
                        profile_id = int(row["profile_id"])
                        permanent_dir = tenant_path / "sessions" / str(profile_id)
                        for filename in m._SESSION_FILES:
                            current = permanent_dir / filename
                            backup = permanent_dir / f"{filename}{m._REAUTH_BACKUP_SUFFIX}"
                            current.unlink(missing_ok=True)
                            if backup.exists():
                                os.replace(backup, current)
                        if int(row["created_profile"] or 0):
                            conn.execute("DELETE FROM profiles WHERE id=? AND NOT EXISTS (SELECT 1 FROM group_profiles WHERE profile_id=?)", (profile_id, profile_id))
                        conn.execute("UPDATE onboarding_sessions SET state='waiting_membership', promotion_state='restored', profile_id=NULL, updated_at=? WHERE id=?", (_iso(_now()), sid))
                        recovered += 1
                    if str(row["expires_at"]) <= _iso(_now()) and str(row["state"]) != "completed":
                        conn.execute(
                            "UPDATE onboarding_sessions SET state='expired', updated_at=?, phone=NULL, full_name=NULL, "
                            "consent_at=NULL, max_user_id=NULL, auth_attempt_id=NULL, session_token_hash='expired:' || id "
                            "WHERE id=?",
                            (_iso(_now()), sid),
                        )
                        if directory.is_dir() and directory.parent == tenant_path / "sessions" / "onboarding":
                            shutil.rmtree(directory, ignore_errors=True)
                        conn.execute(
                            "DELETE FROM onboarding_sessions WHERE id=? AND NOT EXISTS "
                            "(SELECT 1 FROM onboarding_consents WHERE session_id=?)",
                            (sid, sid),
                        )
                        recovered += 1
                    elif str(row["state"]) == "completed" and str(row["expires_at"]) <= _iso(_now()):
                        conn.execute(
                            "UPDATE onboarding_sessions SET phone=NULL, full_name=NULL, consent_at=NULL, "
                            "max_user_id=NULL, auth_attempt_id=NULL, session_token_hash='completed:' || id WHERE id=?",
                            (sid,),
                        )
                        if directory.is_dir() and directory.parent == tenant_path / "sessions" / "onboarding":
                            shutil.rmtree(directory, ignore_errors=True)
                        recovered += 1
                conn.commit()
    return recovered


async def onboarding_cleanup_loop() -> None:
    while True:
        await asyncio.sleep(600)
        try:
            await asyncio.to_thread(recover_and_cleanup_onboarding)
            await _prune_onboarding_runtime()
        except Exception:
            # Cleanup is best-effort; each request still checks expiry in SQLite.
            continue


async def _prune_onboarding_runtime() -> None:
    """Drop expired/completed auth state and cancel abandoned auth workers."""
    from app.tenant import tenant_scope

    session_ids = set(_AUTH_RUNTIME) | set(_AUTH_TASKS)
    for session_id in session_ids:
        runtime = _AUTH_RUNTIME.get(session_id) or {}
        tenant_id = runtime.get("tenant_id")
        row = None
        if tenant_id is not None:
            with tenant_scope(tenant_id=int(tenant_id), role="admin"):
                with m._conn() as conn:
                    try:
                        row = OnboardingRepository(conn).get_session(session_id)
                    except sqlite3.OperationalError:
                        row = None
        task = _AUTH_TASKS.get(session_id)
        expired = row is None or str(row["expires_at"]) <= _iso(_now())
        terminal = expired or str(row["state"]) in {"completed", "expired", "interrupted"}
        if terminal:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            _AUTH_RUNTIME.pop(session_id, None)
            _AUTH_TASKS.pop(session_id, None)
            lock = _ONBOARDING_LOCKS.get(session_id)
            if lock is not None and not lock.locked():
                _ONBOARDING_LOCKS.pop(session_id, None)
        elif task is not None and task.done():
            _AUTH_TASKS.pop(session_id, None)
    for session_id, lock in tuple(_ONBOARDING_LOCKS.items()):
        if session_id not in _AUTH_RUNTIME and session_id not in _AUTH_TASKS and not lock.locked():
            _ONBOARDING_LOCKS.pop(session_id, None)


async def cancel_all_onboarding_auth() -> None:
    tasks = [task for task in _AUTH_TASKS.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _check_membership_and_finalize(tenant_id: int, session_id: str, row) -> bool:
    from app.tenant import tenant_scope

    directory = _onboarding_dir(tenant_id, session_id)
    encrypted_path = directory / "session.db.enc"
    if not encrypted_path.is_file():
        raise HTTPException(409, "ONBOARDING_AUTH_REQUIRED")
    with tenant_scope(tenant_id=tenant_id, role="admin"):
        data_dir = m._resolve_data_dir()
        from app.vault import get_fernet

        plaintext_path = directory / "session.db"
        plaintext_path.write_bytes(get_fernet(data_dir).decrypt(encrypted_path.read_bytes()))
        identity = await m._ensure_session_identity(directory, "session.db")
        class SessionOnly:
            async def authenticate(self, _app):
                raise RuntimeError("ONBOARDING_SESSION_INVALID")
        client = m._build_pymax_client(
            phone=str(row["phone"]), work_dir=str(directory), session_name="session.db",
            auth_flow=SessionOnly(), proxy=_onboarding_proxy(tenant_id, session_id, str(row["phone"])), identity=identity,
        )
        try:
            gateway = m._max_gateway(client)
            await gateway.connect()
            target_id = str(row["max_chat_id"] or "")
            if not target_id.isdigit():
                raise HTTPException(409, "DESTINATION_REVIEW_REQUIRED")
            chat = await gateway.check_destination(chat_id=int(target_id))
            current_user = str(getattr(getattr(client.me, "contact", None), "id", ""))
            if current_user != str(row["max_user_id"] or ""):
                raise HTTPException(409, "ONBOARDING_ACCOUNT_CHANGED")
            if not _member_proof(chat, target_id):
                _persist_state(tenant_id, session_id, "waiting_membership")
                return False
        finally:
            try:
                await m._safe_stop(client)
            except Exception:
                pass
            if plaintext_path.is_file():
                temp_enc = directory / "session.db.enc.tmp"
                temp_enc.write_bytes(get_fernet(data_dir).encrypt(plaintext_path.read_bytes()))
                os.replace(temp_enc, encrypted_path)
            plaintext_path.unlink(missing_ok=True)
            (directory / "session.db-wal").unlink(missing_ok=True)
            (directory / "session.db-shm").unlink(missing_ok=True)

        phone = str(row["phone"])
        created_profile = False
        with tenant_conn(tenant_id) as conn:
            existing = conn.execute("SELECT * FROM profiles WHERE phone=?", (phone,)).fetchone()
            if existing and str(existing["status"]).lower() in {"disabled", "banned", "blocked"}:
                raise HTTPException(409, "PROFILE_DISABLED")
            if existing and bool(row["name_confirmation_required"]) and not str(row["full_name"] or "").strip():
                raise HTTPException(409, "PROFILE_NAME_CONFIRMATION_REQUIRED")
            profile_id = int(existing["id"]) if existing else int(
                conn.execute(
                    "INSERT INTO profiles(phone, full_name, label, status, proxy) VALUES (?, ?, '', ?, '')",
                    (phone, str(row["full_name"]), str(m.ProfileStatus.PENDING)),
                ).lastrowid
            )
            created_profile = existing is None
            if created_profile:
                conn.commit()
        with tenant_scope(tenant_id=tenant_id, role="admin"):
            permanent_dir = m._session_dir(profile_id)
            permanent_dir.mkdir(parents=True, exist_ok=True)
            permanent_enc = permanent_dir / "session.db.enc"
            async with m._profile_client_lock(profile_id):
                staged = m._stage_session_for_reauth(profile_id)
                finalized = False
                _persist_state(tenant_id, session_id, "finalizing", profile_id=profile_id, created_profile=int(created_profile), promotion_state="promoting")
                try:
                    temp_promoted = permanent_dir / "session.db.enc.tmp"
                    shutil.copy2(encrypted_path, temp_promoted)
                    os.replace(temp_promoted, permanent_enc)
                    _persist_state(tenant_id, session_id, "finalizing", promotion_state="promoted")

                    async def validate_profile_session(client):
                        if not client.me or not client.me.contact or str(client.me.contact.id) != str(row["max_user_id"]):
                            raise RuntimeError("ONBOARDING_ACCOUNT_CHANGED")
                        return True

                    await m._with_client_unlocked(
                        profile_id, phone, validate_profile_session,
                        group_id=int(row["group_id"]),
                        proxy=_onboarding_proxy(tenant_id, session_id, phone),
                    )
                    with tenant_conn(tenant_id) as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        current = conn.execute("SELECT status FROM profiles WHERE id=?", (profile_id,)).fetchone()
                        if current is None or str(current["status"]).lower() in {"disabled", "banned", "blocked"}:
                            raise ValueError("PROFILE_DISABLED")
                        conn.execute("UPDATE profiles SET full_name=?, status=?, last_error='' WHERE id=?", (str(row["full_name"]), str(m.ProfileStatus.ACTIVE), profile_id))
                        scope = conn.execute("SELECT automation_group_id FROM profile_automation_scope WHERE profile_id=?", (profile_id,)).fetchone()
                        if scope is None:
                            conn.execute("INSERT INTO profile_automation_scope(profile_id, automation_group_id, consent_state, revision) VALUES (?, ?, 'active', 1)", (profile_id, int(row["group_id"])))
                        elif scope["automation_group_id"] is None:
                            conn.execute("UPDATE profile_automation_scope SET automation_group_id=?, consent_state='active', revision=revision+1 WHERE profile_id=?", (int(row["group_id"]), profile_id))
                        repo = OnboardingRepository(conn)
                        repo.record_successful_use(session_id, int(row["group_id"]), profile_id, now=_iso(_now()))
                        conn.commit()
                    finalized = True
                    with __import__("contextlib").suppress(OSError):
                        m._discard_staged_session(staged)
                    _persist_state(tenant_id, session_id, "completed", promotion_state="complete", profile_id=profile_id)
                    return True
                except Exception:
                    if finalized:
                        _persist_state(tenant_id, session_id, "completed", promotion_state="complete", profile_id=profile_id)
                        return True
                    m._restore_staged_session(staged)
                    with tenant_conn(tenant_id) as conn:
                        if created_profile:
                            conn.execute("DELETE FROM profiles WHERE id=? AND NOT EXISTS (SELECT 1 FROM group_profiles WHERE profile_id=?)", (profile_id, profile_id))
                    _persist_state(tenant_id, session_id, "waiting_membership", promotion_state="restored", profile_id=None)
                    raise
