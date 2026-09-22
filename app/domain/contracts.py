"""Shared storage-scope contracts for local, global, and tenant data."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Mapping


class Scope(str, Enum):
    LOCAL = "local"
    GLOBAL = "global"
    TENANT = "tenant"


def resolve_data_root(settings: Mapping[str, object]) -> Path:
    """Resolve MAX_DATA as a base root, never as a tenant directory."""
    raw = str(settings.get("MAX_DATA") or "").strip()
    if raw:
        return Path(raw)
    root = Path(str(settings.get("ROOT") or "."))
    return root / "data"


def resolve_scope_dir(
    root: Path,
    scope: Scope | str,
    *,
    tenant_id: int | None = None,
) -> Path:
    """Resolve one scope below a base root without sharing tenant paths."""
    scope = Scope(scope)
    if scope is Scope.LOCAL:
        if tenant_id is not None:
            raise ValueError("local_scope_has_no_tenant")
        return root
    if scope is Scope.GLOBAL:
        if tenant_id is not None:
            raise ValueError("global_scope_has_no_tenant")
        return root / "global"
    if tenant_id is None or isinstance(tenant_id, bool) or tenant_id < 1:
        raise ValueError("tenant_id_required")
    return root / "tenants" / str(tenant_id)


def legacy_scope_manifest(
    path: Path,
    scope: Scope | str,
    *,
    tenant_id: int | None = None,
) -> dict[str, object]:
    """Describe an ambiguous legacy path without moving or distributing it."""
    resolved_scope = Scope(scope)
    if tenant_id is not None and (isinstance(tenant_id, bool) or tenant_id < 1):
        raise ValueError("tenant_id_invalid")
    return {
        "path": str(path),
        "scope": resolved_scope.value,
        "tenant_id": tenant_id,
        "status": "BLOCKED" if path.exists() else "NOT_FOUND",
        "reason": "ambiguous_legacy_scope" if path.exists() else "legacy_path_absent",
    }
