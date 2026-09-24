"""Backup/restore checks for plaintext sessions and portable JWT revocation state."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import tarfile

from app import auth_epoch


class UnsafeBackup(RuntimeError):
    """Backup or restore must stop rather than expose credentials or accept stale JWTs."""


def check_data_tree(data_root: Path) -> None:
    for path in data_root.rglob("session.db"):
        raise UnsafeBackup(f"plaintext session.db found: {path}")


def check_data_archive(archive_path: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            if Path(member.name).name == "session.db":
                raise UnsafeBackup(f"plaintext session.db in archive: {member.name}")


def export_auth_state(destination: Path) -> None:
    """Save only JWT epoch, never recovery hold or authorization records."""
    epoch = auth_epoch.current_epoch()
    payload = {"schema_version": 1, "epoch": epoch}
    if destination == Path("-"):
        json.dump(payload, sys.stdout, separators=(",", ":"))
        sys.stdout.write("\n")
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(destination, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _snapshot_epoch(source: Path) -> float:
    if not source.exists():
        return 0.0  # Legacy backup: rotate anyway.
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        if payload["schema_version"] != 1:
            raise ValueError("unsupported auth state")
        epoch = float(payload["epoch"])
        if not math.isfinite(epoch) or epoch < 0:
            raise ValueError("invalid auth epoch")
        return epoch
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise UnsafeBackup("invalid backup auth state") from exc


def rotate_auth_after_restore(source: Path, revision: str) -> float:
    """Advance beyond source and destination epochs before starting restored app."""
    floor = _snapshot_epoch(source)
    return auth_epoch.write_epoch(f"restore:{revision}", minimum_epoch=floor)


def preflight_restore(source: Path) -> None:
    """Validate restore auth input and control-volume access before data changes."""
    _snapshot_epoch(source)
    preflight_control()


def validate_auth_snapshot(source: Path) -> None:
    """Validate a snapshot when the backup directory is readable only by root."""
    _snapshot_epoch(source)


def preflight_control() -> None:
    """Prove the application UID can read and write its control volume."""
    current_epoch = auth_epoch.auth_epoch_file()
    if current_epoch is None:
        raise UnsafeBackup("server auth epoch path is unavailable")
    try:
        auth_epoch.current_epoch()
        if not current_epoch.parent.is_dir():
            raise UnsafeBackup("server control volume is unavailable")
        descriptor, probe = tempfile.mkstemp(
            prefix=".restore-auth-preflight.", dir=current_epoch.parent
        )
        os.close(descriptor)
        Path(probe).unlink()
    except OSError as exc:
        raise UnsafeBackup("server control volume is not writable") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "check-tree",
            "check-archive",
            "export-auth",
            "preflight-restore",
            "rotate-auth",
            "validate-auth-snapshot",
            "preflight-control",
        ),
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--revision", default="")
    args = parser.parse_args(argv)
    try:
        if args.command == "check-tree":
            check_data_tree(args.path)
        elif args.command == "check-archive":
            check_data_archive(args.path)
        elif args.command == "export-auth":
            export_auth_state(args.path)
        elif args.command == "preflight-restore":
            preflight_restore(args.path)
        elif args.command == "validate-auth-snapshot":
            validate_auth_snapshot(args.path)
        elif args.command == "preflight-control":
            preflight_control()
        else:
            rotate_auth_after_restore(args.path, args.revision)
    except (UnsafeBackup, auth_epoch.AuthEpochInvalid, OSError, ValueError) as exc:
        parser.exit(1, f"backup safety check failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
