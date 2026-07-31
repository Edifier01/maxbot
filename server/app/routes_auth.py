"""Auth API: регистрация, вход, профиль."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from app import auth, db_pg
from app.config import is_server_mode
from app.runtime import main as app_main

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    institution_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    password_confirm: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


def _token_response(user: dict) -> dict:
    token = auth.create_token(
        user["id"],
        tenant_id=user.get("tenant_id"),
        role=user["role"],
    )
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


@router.post("/register")
async def register(body: RegisterIn):
    if not is_server_mode():
        raise HTTPException(400, "Регистрация доступна только на сервере")
    if os.environ.get("REGISTRATION_OPEN", "1").strip().lower() not in (
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
    return _token_response(user)


@router.post("/login")
async def login(body: LoginIn):
    if not is_server_mode():
        raise HTTPException(400, "Вход доступен только на сервере")
    user = auth.authenticate(body.email, body.password)
    if not user:
        raise HTTPException(401, "Неверный email или пароль")

    if user.get("tenant_id"):
        from app.tenant_init import init_tenant_db

        init_tenant_db(app_main, user["tenant_id"])

    return _token_response(user)


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("max_token", "")


@router.post("/logout")
async def logout(request: Request):
    if not is_server_mode():
        return {"ok": True}
    token = _bearer_token(request)
    if not token:
        raise HTTPException(401, "Требуется вход")
    try:
        payload = auth.decode_token(token)
    except Exception as e:
        raise HTTPException(401, "Сессия истекла") from e
    jti = payload.get("jti")
    if jti:
        db_pg.revoke_token(jti, auth.token_expires_at(payload))
    return {"ok": True}


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
    return {
        "server_mode": True,
        "user_id": user_id,
        "email": user["email"],
        "role": get_user_role(),
        "tenant_id": tenant_id,
        "institution_name": tenant["institution_name"] if tenant else None,
        "subscription": db_pg.subscription_info(tenant_id),
        "impersonating": is_impersonating(),
    }
