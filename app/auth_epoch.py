"""Persistent server-wide JWT epoch for explicit administrator recovery."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time
import uuid
from typing import Any


class AuthEpochInvalid(RuntimeError):
    """The control record is malformed and authentication must fail closed."""


def auth_epoch_file() -> Path | None:
    from app.config import auth_epoch_file as configured_auth_epoch_file

    return configured_auth_epoch_file()


def current_epoch() -> float:
    path = auth_epoch_file()
    if path is None:
        return 0.0
    try:
        path.stat()
        if not path.is_file():
            raise AuthEpochInvalid("auth_epoch_invalid")
        payload = json.loads(path.read_text(encoding="utf-8"))
        epoch = float(payload["epoch"])
    except FileNotFoundError:
        return 0.0
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AuthEpochInvalid("auth_epoch_invalid") from exc
    if not math.isfinite(epoch) or epoch <= 0:
        raise AuthEpochInvalid("auth_epoch_invalid")
    return epoch


def token_iat_epoch(payload: dict[str, Any]) -> float | None:
    value = payload.get("iat")
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def token_is_current(payload: dict[str, Any]) -> bool:
    epoch = current_epoch()
    if epoch == 0.0:
        return True
    claimed_epoch = payload.get("ae")
    if claimed_epoch is not None:
        try:
            return math.isclose(float(claimed_epoch), epoch, rel_tol=0.0, abs_tol=1e-6)
        except (TypeError, ValueError):
            return False
    issued_at = token_iat_epoch(payload)
    return issued_at is not None and issued_at >= epoch


def write_epoch(authorization_reference: str, *, minimum_epoch: float = 0.0) -> float:
    reference = authorization_reference.strip()
    if not reference or len(reference) > 200 or not reference.isprintable():
        raise ValueError("authorization reference must be non-empty and printable")
    path = auth_epoch_file()
    if path is None:
        raise RuntimeError("MAX_SERVER_MODE=1 is required for administrator recovery")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not math.isfinite(minimum_epoch) or minimum_epoch < 0:
        raise ValueError("invalid minimum auth epoch")
    epoch = max(time.time(), current_epoch(), minimum_epoch) + 1.0
    payload = {
        "schema_version": 1,
        "epoch": epoch,
        "authorization_reference": reference,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    temporary = path.with_name(f".auth-epoch.{uuid.uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary, flags, 0o640)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(payload, stream, ensure_ascii=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if hasattr(os, "chown") and os.geteuid() == 0:
            os.chown(temporary, 10001, 10001)
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return epoch
