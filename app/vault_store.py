"""In-memory Fernet cache per data-dir (server multi-tenant vault)."""

from __future__ import annotations

import threading
from pathlib import Path

from cryptography.fernet import Fernet

_vault_by_data: dict[str, tuple[Fernet | None, bool]] = {}
_vault_lock = threading.Lock()


def store_key(data_dir: Path) -> str:
    return str(data_dir)


def get(key: str) -> tuple[Fernet | None, bool]:
    with _vault_lock:
        return _vault_by_data.get(key, (None, False))


def set_state(key: str, fernet: Fernet | None, unlocked: bool) -> None:
    with _vault_lock:
        _vault_by_data[key] = (fernet, unlocked)


def clear_all() -> None:
    with _vault_lock:
        _vault_by_data.clear()
