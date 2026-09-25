#!/usr/bin/env python3
"""Atomically create one external-action recovery hold."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import recovery_hold_file  # noqa: E402
from app.recovery_hold import load_recovery_hold  # noqa: E402


def _safe_text(value: str, name: str) -> str:
    value = value.strip()
    if not value or len(value) > 200 or not value.isprintable():
        raise ValueError(f"{name} must be non-empty printable text up to 200 characters")
    return value


def create_hold(path: Path, *, revision: str, reason: str) -> tuple[str, bool]:
    revision = _safe_text(revision, "revision")
    reason = _safe_text(reason, "reason")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "revision": revision,
        "reason": reason,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
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
        # Hard-link creation is atomic; preserve a valid hold from an earlier run.
        try:
            os.link(temporary, path)
        except FileExistsError:
            existing = load_recovery_hold(path)
            if existing is None:
                raise RuntimeError("recovery hold disappeared during creation")
            return existing.revision, False
        return revision, True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    path = recovery_hold_file()
    if path is None:
        parser.error("MAX_SERVER_MODE=1 or MAX_RECOVERY_HOLD_FILE is required")
    try:
        active_revision, created = create_hold(
            path, revision=args.revision, reason=args.reason
        )
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"recovery hold creation failed: {exc}\n")
    if created:
        print(f"Recovery hold active; revision={active_revision}")
    else:
        print(f"Existing recovery hold preserved; revision={active_revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
