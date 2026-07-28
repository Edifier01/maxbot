"""Контекст tenant/user для серверного режима."""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path

_tenant_id: ContextVar[int | None] = ContextVar("tenant_id", default=None)
_user_id: ContextVar[int | None] = ContextVar("user_id", default=None)
_user_role: ContextVar[str] = ContextVar("user_role", default="")
_impersonating: ContextVar[bool] = ContextVar("impersonating", default=False)
_use_global_data: ContextVar[bool] = ContextVar("use_global_data", default=False)


def set_context(
    *,
    user_id: int | None = None,
    tenant_id: int | None = None,
    role: str = "",
    impersonating: bool = False,
    use_global_data: bool = False,
) -> None:
    _user_id.set(user_id)
    _tenant_id.set(tenant_id)
    _user_role.set(role)
    _impersonating.set(impersonating)
    _use_global_data.set(use_global_data)


def clear_context() -> None:
    set_context()


def get_tenant_id() -> int | None:
    return _tenant_id.get()


def get_user_id() -> int | None:
    return _user_id.get()


def get_user_role() -> str:
    return _user_role.get()


def is_admin() -> bool:
    return _user_role.get() == "admin"


def is_impersonating() -> bool:
    return _impersonating.get()


def use_global_data() -> bool:
    return _use_global_data.get()


def get_effective_data_dir(root: Path) -> Path:
    if _use_global_data.get():
        return root / "data" / "global"
    tid = _tenant_id.get()
    if tid is not None:
        return root / "data" / "tenants" / str(tid)
    return root / "data"
