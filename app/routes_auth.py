"""Auth API: регистрация, вход, профиль."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from starlette.responses import JSONResponse

from app import auth, db_pg
from app.auth_cookies import (
    clear_admin_backup_cookie,
    clear_auth_cookie,
    set_auth_cookie,
)
from app.config import is_server_mode
from app.runtime import main as app_main

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    institution_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    password_confirm: str = Field(min_length=8, max_length=128)
    remember_me: bool = True


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    remember_me: bool = True


def _session_payload(user: dict, token: str) -> dict:
    sub = db_pg.subscription_info(user.get("tenant_id"))
    tenant = None
    if user.get("tenant_id"):
        tenant = db_pg.get_tenant(user["tenant_id"])
    return {
        "token": token,
        "role": user["role"],
        "email": user["email"],
        "tenant_id": user.get("tenant_id"),
        "institution_name": tenant["institution_name"] if tenant else None,
        "subscription": sub,
    }


def _token_response(user: dict) -> dict:
    token = auth.create_token(
        user["id"],
        tenant_id=user.get("tenant_id"),
        role=user["role"],
    )
    return _session_payload(user, token)


def _auth_json_response(
    data: dict,
    request: Request,
    *,
    remember_me: bool,
) -> JSONResponse:
    response = JSONResponse(content=data)
    set_auth_cookie(response, data["token"], remember_me=remember_me, request=request)
    return response


@router.post("/register")
async def register(body: RegisterIn, request: Request):
    if not is_server_mode():
        raise HTTPException(400, "Регистрация доступна только на сервере")
    if os.environ.get("REGISTRATION_OPEN", "0").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        raise HTTPException(
            403, "Регистрация закрыта. Обратитесь к администратору."
        )
    if body.password != body.password_confirm:
        raise HTTPException(400, "Пароли не совпадают")
    try:
        info = auth.register_user(body.institution_name, body.email, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    from app.tenant_init import init_tenant_db, rollback_tenant_registration

    try:
        init_tenant_db(app_main, info["tenant_id"])
    except Exception:
        rollback_tenant_registration(info["tenant_id"], app_main.ROOT)
        raise HTTPException(
            500, "Не удалось инициализировать кабинет. Попробуйте позже."
        ) from None

    user = db_pg.get_user_by_id(info["user_id"])
    if not user:
        raise HTTPException(500, "Не удалось создать пользователя")
    data = _token_response(user)
    return _auth_json_response(data, request, remember_me=body.remember_me)


@router.post("/login")
async def login(body: LoginIn, request: Request):
    if not is_server_mode():
        raise HTTPException(400, "Вход доступен только на сервере")
    user = auth.authenticate(body.email, body.password)
    if not user:
        raise HTTPException(401, "Неверный email или пароль")

    if user.get("tenant_id"):
        from app.tenant_init import init_tenant_db

        init_tenant_db(app_main, user["tenant_id"])

    data = _token_response(user)
    return _auth_json_response(data, request, remember_me=body.remember_me)


@router.post("/restore-session")
async def restore_session(request: Request):
    if not is_server_mode():
        raise HTTPException(400, "Восстановление сессии доступно только на сервере")
    token = request.cookies.get("max_token", "")
    if not token:
        raise HTTPException(401, "Требуется вход")
    try:
        payload = auth.decode_token(token)
    except Exception as e:
        raise HTTPException(401, "Сессия истекла") from e
    if payload.get("imp"):
        raise HTTPException(401, "Сессия недоступна")
    session_err = auth.validate_token_session(payload)
    if session_err:
        raise HTTPException(401, session_err)
    user = db_pg.get_user_by_id(int(payload["sub"]))
    if not user:
        raise HTTPException(401, "Пользователь не найден")
    if user.get("tenant_id"):
        from app.tenant_init import init_tenant_db

        init_tenant_db(app_main, user["tenant_id"])
    return _session_payload(user, token)


def _user_cookie_token(request: Request) -> str:
    return (request.cookies.get("max_token") or "").strip()


@router.post("/exit-impersonation")
async def exit_impersonation(request: Request):
    if not is_server_mode():
        raise HTTPException(400, "Выход из impersonation доступен только на сервере")
    admin_token = (request.cookies.get("max_admin_token") or "").strip()
    if not admin_token:
        raise HTTPException(401, "Требуется вход")
    try:
        payload = auth.decode_token(admin_token)
    except Exception as e:
        raise HTTPException(401, "Сессия истекла") from e
    if payload.get("imp"):
        raise HTTPException(401, "Сессия недоступна")
    session_err = auth.validate_token_session(payload)
    if session_err:
        raise HTTPException(401, session_err)
    user = db_pg.get_user_by_id(int(payload["sub"]))
    if not user:
        raise HTTPException(401, "Пользователь не найден")
    data = _session_payload(user, admin_token)
    response = JSONResponse(content=data)
    set_auth_cookie(response, admin_token, remember_me=False, request=request)
    clear_admin_backup_cookie(response, request)
    return response


@router.post("/logout")
async def logout(request: Request):
    if not is_server_mode():
        response = JSONResponse(content={"ok": True})
        clear_auth_cookie(response, request)
        clear_admin_backup_cookie(response, request)
        return response
    token = _user_cookie_token(request)
    if not token:
        raise HTTPException(401, "Требуется вход")
    try:
        payload = auth.decode_token(token)
    except Exception as e:
        raise HTTPException(401, "Сессия истекла") from e
    jti = payload.get("jti")
    if jti:
        db_pg.revoke_token(jti, auth.token_expires_at(payload))
        auth.invalidate_session_cache(jti)
    response = JSONResponse(content={"ok": True})
    clear_auth_cookie(response, request)
    clear_admin_backup_cookie(response, request)
    return response


@router.get("/me")
async def me(request: Request):
    if not is_server_mode():
        return {"server_mode": False, "role": "local"}
    from app.tenant import (
        get_tenant_id,
        get_user_id,
        get_user_role,
        is_impersonating,
    )

    user_id = get_user_id()
    if user_id is None:
        raise HTTPException(401, "Требуется вход")
    user = db_pg.get_user_by_id(user_id)
    if not user:
        raise HTTPException(401, "Пользователь не найден")
    tenant_id = get_tenant_id()
    tenant = db_pg.get_tenant(tenant_id) if tenant_id else None
    email = user["email"]
    actor_email = None
    if is_impersonating() and tenant_id is not None:
        tenant_user = db_pg.get_tenant_user(tenant_id)
        if tenant_user:
            actor_email = email
            email = tenant_user["email"]
    payload = {
        "server_mode": True,
        "user_id": user_id,
        "email": email,
        "role": get_user_role(),
        "tenant_id": tenant_id,
        "institution_name": tenant["institution_name"] if tenant else None,
        "subscription": db_pg.subscription_info(tenant_id),
        "impersonating": is_impersonating(),
    }
    if actor_email is not None:
        payload["actor_email"] = actor_email
    return payload
