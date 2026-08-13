"""Vault API: PBKDF2 Fernet, setup/unlock/lock, session file crypto."""

from __future__ import annotations

import base64
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app import paths, vault_store

VAULT_MAGIC = b"max-sender-v1"
LogFn = Callable[[str], None]


def derive_fernet(password: str, salt: bytes) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))
    return Fernet(key)


def _key(data_dir: Path) -> str:
    return vault_store.store_key(data_dir)


def get_state(data_dir: Path) -> tuple[Fernet | None, bool]:
    return vault_store.get(_key(data_dir))


def set_state(data_dir: Path, fernet: Fernet | None, unlocked: bool) -> None:
    vault_store.set_state(_key(data_dir), fernet, unlocked)


def clear_cache() -> None:
    vault_store.clear_all()


def status(data_dir: Path) -> dict[str, Any]:
    ensure_vault_unlocked(data_dir)
    key_path = paths.app_key_path(data_dir)
    fernet, unlocked = get_state(data_dir)
    return {
        "unlocked": bool(unlocked and fernet is not None),
        "protected": False,
        "legacy": key_path.exists(),
        "needs_setup": False,
    }


def _drop_password_vault_files(data_dir: Path) -> None:
    # ponytail: PBKDF2 vault removed; encrypted sessions need MAX re-login
    paths.app_salt_path(data_dir).unlink(missing_ok=True)
    paths.app_vault_path(data_dir).unlink(missing_ok=True)


def ensure_vault_unlocked(data_dir: Path, log: LogFn | None = None) -> None:
    """Auto-unlock via machine-local .app_key (no user password)."""
    _, unlocked = get_state(data_dir)
    if unlocked:
        return
    data_dir.mkdir(parents=True, exist_ok=True)
    paths.sessions_root(data_dir).mkdir(parents=True, exist_ok=True)
    salt_path = paths.app_salt_path(data_dir)
    key_path = paths.app_key_path(data_dir)
    if salt_path.exists():
        _drop_password_vault_files(data_dir)
        if log:
            log("Хранилище: режим с паролем отключён, используется .app_key")
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
    try:
        set_state(data_dir, Fernet(key_path.read_bytes()), True)
    except Exception as e:
        if log:
            log(f"Хранилище: не удалось загрузить .app_key: {e}")


def try_legacy_unlock(data_dir: Path, log: LogFn | None = None) -> None:
    ensure_vault_unlocked(data_dir, log)


def get_fernet(data_dir: Path) -> Fernet:
    fernet, unlocked = get_state(data_dir)
    if fernet is None or not unlocked:
        raise RuntimeError("Хранилище сессий недоступно — не удалось загрузить .app_key")
    return fernet


def reencrypt_all_sessions(data_dir: Path, old_f: Fernet, new_f: Fernet) -> int:
    """Перешифровать все session.db.enc со старого ключа на новый."""
    n = 0
    sessions = paths.sessions_root(data_dir)
    if not sessions.exists():
        return 0
    for d in sessions.iterdir():
        if not d.is_dir():
            continue
        enc = d / "session.db.enc"
        db = d / "session.db"
        if db.exists() and not enc.exists():
            try:
                enc.write_bytes(old_f.encrypt(db.read_bytes()))
                db.unlink(missing_ok=True)
            except Exception:
                continue
        if not enc.exists():
            continue
        try:
            plain = old_f.decrypt(enc.read_bytes())
            enc.write_bytes(new_f.encrypt(plain))
            n += 1
        except InvalidToken:
            continue
        except OSError:
            continue
    return n


def setup(data_dir: Path, password: str, log: LogFn | None = None) -> dict[str, Any]:
    """Legacy password-vault setup API (PBKDF2); panel uses .app_key auto-unlock."""
    if len(password) < 6:
        raise ValueError("Пароль хранилища должен быть не короче 6 символов")
    if paths.app_salt_path(data_dir).exists():
        raise ValueError("Хранилище уже защищено — используйте разблокировку")

    data_dir.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(16)
    new_f = derive_fernet(password, salt)
    migrated = 0
    key_path = paths.app_key_path(data_dir)
    if key_path.exists():
        old_f = Fernet(key_path.read_bytes())
        migrated = reencrypt_all_sessions(data_dir, old_f, new_f)
        key_path.unlink(missing_ok=True)

    paths.app_salt_path(data_dir).write_bytes(salt)
    paths.app_vault_path(data_dir).write_bytes(new_f.encrypt(VAULT_MAGIC))
    set_state(data_dir, new_f, True)
    if log:
        msg = "Хранилище защищено паролем"
        if migrated:
            msg += f" (перешифровано сессий: {migrated})"
        log(msg)
    return {"ok": True, "migrated_sessions": migrated}


def unlock(data_dir: Path, password: str, log: LogFn | None = None) -> None:
    salt_path = paths.app_salt_path(data_dir)
    vault_path = paths.app_vault_path(data_dir)
    if not salt_path.exists():
        raise ValueError("Сначала задайте пароль хранилища")
    salt = salt_path.read_bytes()
    candidate = derive_fernet(password, salt)
    if not vault_path.exists():
        raise ValueError("Повреждён файл хранилища (.app_vault)")
    try:
        magic = candidate.decrypt(vault_path.read_bytes())
    except InvalidToken as e:
        raise ValueError("Неверный пароль хранилища") from e
    if magic != VAULT_MAGIC:
        raise ValueError("Неверный пароль хранилища")
    set_state(data_dir, candidate, True)
    if log:
        log("Хранилище разблокировано")


def lock(
    data_dir: Path,
    *,
    encrypt_sessions: Callable[[], None] | None = None,
    log: LogFn | None = None,
) -> None:
    _, unlocked = get_state(data_dir)
    if unlocked and encrypt_sessions:
        encrypt_sessions()
    set_state(data_dir, None, False)
    if log:
        log("Хранилище заблокировано")


def ready_for_send(data_dir: Path) -> bool:
    st = status(data_dir)
    return bool(st["unlocked"])


def session_dir(data_dir: Path, profile_id: int) -> Path:
    d = paths.sessions_root(data_dir) / str(profile_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def decrypt_session_file(data_dir: Path, profile_id: int, log: LogFn | None = None) -> None:
    d = session_dir(data_dir, profile_id)
    db, enc = d / "session.db", d / "session.db.enc"
    if not enc.exists() or db.exists():
        return
    try:
        db.write_bytes(get_fernet(data_dir).decrypt(enc.read_bytes()))
    except InvalidToken:
        enc.unlink(missing_ok=True)
        if log:
            log(f"Профиль #{profile_id}: не удалось расшифровать сессию — войдите заново")
    except RuntimeError as e:
        if log:
            log(f"Профиль #{profile_id}: {e}")
        raise


def encrypt_session_file(data_dir: Path, profile_id: int, log: LogFn | None = None) -> None:
    d = session_dir(data_dir, profile_id)
    db, enc = d / "session.db", d / "session.db.enc"
    if not db.exists():
        return
    try:
        enc.write_bytes(get_fernet(data_dir).encrypt(db.read_bytes()))
        db.unlink(missing_ok=True)
    except RuntimeError:
        # ponytail: shutdown без unlock — не трогаем plaintext
        pass
    except OSError as e:
        if log:
            log(f"Профиль #{profile_id}: ошибка шифрования сессии: {e}")
