"""Пути внутри data-dir (чистые функции, без globals)."""

from __future__ import annotations

from pathlib import Path


def sessions_root(data_dir: Path) -> Path:
    return data_dir / "sessions"


def messages_file(data_dir: Path) -> Path:
    return data_dir / "messages" / "active.txt"


def db_path(data_dir: Path) -> Path:
    return data_dir / "app.db"


def app_key_path(data_dir: Path) -> Path:
    return data_dir / ".app_key"


def app_salt_path(data_dir: Path) -> Path:
    return data_dir / ".app_salt"


def app_vault_path(data_dir: Path) -> Path:
    return data_dir / ".app_vault"


def backups_dir(data_dir: Path) -> Path:
    return data_dir / "backups"
