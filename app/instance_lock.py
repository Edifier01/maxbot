"""Single campaign-owner guard for the shared server data volume."""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO

_lock_file: IO[str] | None = None


def acquire(root: Path) -> None:
    """Fail closed when another server process owns the shared data volume."""
    global _lock_file
    if os.environ.get("MAX_TEST") == "1" or _lock_file is not None:
        return
    try:
        import fcntl
    except ImportError as exc:  # pragma: no cover - production image is Linux
        raise RuntimeError("Server instance lock requires POSIX flock") from exc

    lock_path = root / "data" / ".app-instance.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError(
            "Another MAX Sender app instance already owns max_server_data"
        ) from exc
    handle.seek(0)
    handle.truncate()
    handle.write(f"pid={os.getpid()}\n")
    handle.flush()
    _lock_file = handle


def release() -> None:
    global _lock_file
    handle, _lock_file = _lock_file, None
    if handle is None:
        return
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
