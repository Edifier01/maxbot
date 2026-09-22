"""Explicit, lossless migration from the legacy password vault to .app_key."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3

from cryptography.fernet import Fernet, InvalidToken

from app import paths, vault


class VaultMigrationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class VaultMigrationPlan:
    data_dir: Path
    staged_files: tuple[Path, ...]
    session_digests: dict[str, str]
    _new_key: bytes = field(repr=False)
    _new_fernet: Fernet = field(repr=False)
    _source_files: tuple[Path, ...] = field(repr=False)
    archive_dir: Path | None = None
    status: str = "PREPARED"


def _fsync_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _legacy_fernet(data_dir: Path, password: str) -> Fernet:
    salt_path = paths.app_salt_path(data_dir)
    vault_path = paths.app_vault_path(data_dir)
    if not salt_path.is_file() or not vault_path.is_file():
        raise VaultMigrationError("MIGRATION_REVIEW_REQUIRED")
    try:
        old = vault.derive_fernet(password, salt_path.read_bytes())
        if old.decrypt(vault_path.read_bytes()) != vault.VAULT_MAGIC:
            raise InvalidToken
    except (InvalidToken, OSError, ValueError) as exc:
        raise VaultMigrationError("VAULT_KEY_REQUIRED") from exc
    return old


def _session_sources(data_dir: Path, old: Fernet) -> tuple[list[Path], dict[str, bytes]]:
    root = paths.sessions_root(data_dir)
    sources: list[Path] = []
    plain: dict[str, bytes] = {}
    if not root.exists():
        return sources, plain
    for session_dir in sorted(root.iterdir()):
        if not session_dir.is_dir():
            continue
        if any((session_dir / sidecar).exists() for sidecar in ("session.db-wal", "session.db-shm")):
            raise VaultMigrationError("STORAGE_ERROR")
        encrypted = session_dir / "session.db.enc"
        plaintext = session_dir / "session.db"
        if encrypted.is_file():
            try:
                payload = old.decrypt(encrypted.read_bytes())
            except (InvalidToken, OSError) as exc:
                raise VaultMigrationError("VAULT_INTEGRITY_FAILED") from exc
            sources.append(encrypted)
            plain[str(encrypted.relative_to(data_dir))] = payload
        elif plaintext.is_file():
            try:
                payload = plaintext.read_bytes()
            except OSError as exc:
                raise VaultMigrationError("STORAGE_ERROR") from exc
            sources.append(plaintext)
            plain[str(plaintext.relative_to(data_dir))] = payload
    return sources, plain


def prepare_migration(data_dir: Path, password: str) -> VaultMigrationPlan:
    """Decrypt and stage every session without changing active legacy files."""
    old = _legacy_fernet(data_dir, password)
    sources, plaintext = _session_sources(data_dir, old)
    new_key = Fernet.generate_key()
    new = Fernet(new_key)
    staged: list[Path] = []
    digests: dict[str, str] = {}
    try:
        for source in sources:
            relative = source.relative_to(data_dir)
            target = source.parent / "session.db.enc.migration.tmp"
            payload = plaintext[str(relative)]
            _fsync_write(target, new.encrypt(payload))
            staged.append(target)
            digests[str(relative)] = hashlib.sha256(payload).hexdigest()
    except (OSError, KeyError) as exc:
        for path in staged:
            path.unlink(missing_ok=True)
        raise VaultMigrationError("STORAGE_ERROR") from exc
    return VaultMigrationPlan(
        data_dir=data_dir,
        staged_files=tuple(staged),
        session_digests=digests,
        _new_key=new_key,
        _new_fernet=new,
        _source_files=tuple(sources),
    )


def verify_migration(plan: VaultMigrationPlan) -> bool:
    if plan.status not in {"PREPARED", "VERIFIED"}:
        raise VaultMigrationError("MIGRATION_REVIEW_REQUIRED")
    if len(plan.staged_files) != len(plan._source_files):
        raise VaultMigrationError("VAULT_INTEGRITY_FAILED")
    for source, staged in zip(plan._source_files, plan.staged_files, strict=True):
        if not staged.is_file():
            raise VaultMigrationError("VAULT_INTEGRITY_FAILED")
        try:
            payload = plan._new_fernet.decrypt(staged.read_bytes())
        except (InvalidToken, OSError) as exc:
            raise VaultMigrationError("VAULT_INTEGRITY_FAILED") from exc
        relative = str(source.relative_to(plan.data_dir))
        if hashlib.sha256(payload).hexdigest() != plan.session_digests.get(relative):
            raise VaultMigrationError("VAULT_INTEGRITY_FAILED")
    plan.status = "VERIFIED"
    return True


def _archive_path(data_dir: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    candidate = data_dir / f"legacy-vault-backup-{stamp}"
    suffix = 0
    while candidate.exists():
        suffix += 1
        candidate = data_dir / f"legacy-vault-backup-{stamp}-{suffix}"
    return candidate


def _restore_from_archive(plan: VaultMigrationPlan, archive: Path) -> None:
    for source in plan._source_files:
        archived = archive / source.relative_to(plan.data_dir)
        if archived.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            if source.exists():
                source.unlink()
            shutil.move(str(archived), str(source))
    for name in (".app_salt", ".app_vault"):
        archived = archive / name
        target = plan.data_dir / name
        if archived.exists():
            if target.exists():
                target.unlink()
            shutil.move(str(archived), str(target))


def commit_migration(plan: VaultMigrationPlan) -> Path:
    """Atomically activate verified files and retain old material in an archive."""
    verify_migration(plan)
    archive = _archive_path(plan.data_dir)
    archive.mkdir(mode=0o700, parents=True, exist_ok=False)
    app_key = paths.app_key_path(plan.data_dir)
    key_tmp = app_key.with_suffix(".migration.tmp")
    replaced: list[Path] = []
    try:
        for source in plan._source_files:
            archived = archive / source.relative_to(plan.data_dir)
            archived.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.move(str(source), str(archived))
        for name in (".app_salt", ".app_vault"):
            legacy = plan.data_dir / name
            if legacy.exists():
                shutil.move(str(legacy), str(archive / name))
        for source, staged in zip(plan._source_files, plan.staged_files, strict=True):
            target = source.parent / "session.db.enc"
            os.replace(staged, target)
            replaced.append(target)
        _fsync_write(key_tmp, plan._new_key)
        os.replace(key_tmp, app_key)
        plan.archive_dir = archive
        plan.status = "COMMITTED"
        vault.clear_cache()
        vault.set_state(plan.data_dir, plan._new_fernet, True)
        return archive
    except (OSError, ValueError) as exc:
        key_tmp.unlink(missing_ok=True)
        for target in replaced:
            target.unlink(missing_ok=True)
        _restore_from_archive(plan, archive)
        shutil.rmtree(archive, ignore_errors=True)
        plan.status = "FAILED"
        raise VaultMigrationError("STORAGE_ERROR") from exc


def rollback_migration(plan: VaultMigrationPlan) -> None:
    """Remove only uncommitted staging files; never erase legacy originals."""
    if plan.status == "COMMITTED":
        raise VaultMigrationError("MIGRATION_REVIEW_REQUIRED")
    for path in plan.staged_files:
        path.unlink(missing_ok=True)
    plan.status = "ROLLED_BACK"
