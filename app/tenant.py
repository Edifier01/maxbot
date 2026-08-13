"""Контекст tenant/user для серверного режима."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

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


@dataclass(frozen=True)
class _ContextSnapshot:
    user_id: int | None
    tenant_id: int | None
    role: str
    impersonating: bool
    use_global_data: bool


def snapshot_context() -> _ContextSnapshot:
    return _ContextSnapshot(
        user_id=get_user_id(),
        tenant_id=get_tenant_id(),
        role=get_user_role(),
        impersonating=is_impersonating(),
        use_global_data=use_global_data(),
    )


def restore_context(snap: _ContextSnapshot) -> None:
    set_context(
        user_id=snap.user_id,
        tenant_id=snap.tenant_id,
        role=snap.role,
        impersonating=snap.impersonating,
        use_global_data=snap.use_global_data,
    )


@contextmanager
def tenant_scope(
    *,
    user_id: int | None = None,
    tenant_id: int | None = None,
    role: str = "",
    impersonating: bool = False,
    use_global_data: bool = False,
) -> Iterator[None]:
    """Временно сменить tenant context и восстановить (P3-1)."""
    saved = snapshot_context()
    set_context(
        user_id=user_id if user_id is not None else saved.user_id,
        tenant_id=tenant_id,
        role=role or saved.role,
        impersonating=impersonating,
        use_global_data=use_global_data,
    )
    try:
        yield
    finally:
        restore_context(saved)


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


def is_cabinet_user() -> bool:
    return get_user_role() == "user" and not is_impersonating()


def use_global_data() -> bool:
    return _use_global_data.get()


def get_effective_data_dir(root: Path) -> Path:
    if _use_global_data.get():
        return root / "data" / "global"
    tid = _tenant_id.get()
    if tid is not None:
        return root / "data" / "tenants" / str(tid)
    return root / "data"
