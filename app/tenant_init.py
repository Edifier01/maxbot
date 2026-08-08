"""Инициализация tenant data dir и глобального хранилища."""

from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet


def ensure_tenant_data(root: Path, tenant_id: int) -> Path:
    data_dir = root / "data" / "tenants" / str(tenant_id)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "sessions").mkdir(exist_ok=True)
    (data_dir / "messages").mkdir(exist_ok=True)
    key_path = data_dir / ".app_key"
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
    return data_dir


def ensure_global_data(root: Path) -> Path:
    data_dir = root / "data" / "global"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "sessions").mkdir(exist_ok=True)
    (data_dir / "messages").mkdir(exist_ok=True)
    key_path = data_dir / ".app_key"
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
    return data_dir


def init_tenant_db(main_module, tenant_id: int) -> None:
    """Инициализировать SQLite для tenant (если ещё не создан)."""
    from app.tenant import tenant_scope

    ensure_tenant_data(main_module.ROOT, tenant_id)
    with tenant_scope(tenant_id=tenant_id, role="user"):
        if not main_module._db_path().exists():
            main_module.init_db()
        main_module._try_legacy_unlock()


def rollback_tenant_registration(tenant_id: int, root: Path) -> None:
    """Откат PG + data dir после неудачной init_tenant_db при register."""
    import shutil

    from app import db_pg

    db_pg.delete_tenant(tenant_id)
    data_dir = root / "data" / "tenants" / str(tenant_id)
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)


def init_global_db(main_module) -> None:
    from app.tenant import tenant_scope

    ensure_global_data(main_module.ROOT)
    with tenant_scope(use_global_data=True, role="admin"):
        # Always migrate: empty file from early _global_conn() has no tables.
        main_module.init_db()
        main_module._try_legacy_unlock()
