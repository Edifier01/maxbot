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
    from server.app.tenant import set_context

    ensure_tenant_data(main_module.ROOT, tenant_id)
    set_context(tenant_id=tenant_id, role="user")
    main_module._refresh_data_paths()
    main_module._reset_db_conn()
    db_path = main_module.DB_PATH
    if not db_path.exists():
        main_module.init_db()
    main_module._try_legacy_unlock()


def init_global_db(main_module) -> None:
    from server.app.tenant import set_context

    ensure_global_data(main_module.ROOT)
    set_context(use_global_data=True, role="admin")
    main_module._refresh_data_paths()
    main_module._reset_db_conn()
    if not main_module.DB_PATH.exists():
        main_module.init_db()
    main_module._try_legacy_unlock()
