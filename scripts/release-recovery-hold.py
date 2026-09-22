#!/usr/bin/env python3
"""Explicitly release one recovery hold after operator authorization."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import recovery_hold  # noqa: E402


def _safe_reference(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 200 or not value.isprintable():
        raise ValueError("authorization reference must be non-empty and printable")
    return value


def release(*, expected_revision: str, authorization_reference: str) -> Path:
    reference = _safe_reference(authorization_reference)
    hold_path = recovery_hold.recovery_hold_file()
    if hold_path is None:
        raise RuntimeError("MAX_RECOVERY_HOLD_FILE is not configured")
    hold = recovery_hold.load_recovery_hold(hold_path)
    if hold is None:
        raise RuntimeError("recovery hold is not active")
    if hold.revision != expected_revision:
        raise RuntimeError("recovery hold revision mismatch")

    evidence_path = hold_path.with_name("recovery-release.jsonl")
    evidence = {
        "schema_version": 1,
        "hold_revision": hold.revision,
        "authorization_reference": reference,
        "released_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    with evidence_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(evidence, ensure_ascii=True, separators=(",", ":")))
        stream.write("\n")
        stream.flush()
        import os

        os.fsync(stream.fileno())

    # unlink removes one directory entry atomically; it never starts a worker.
    hold_path.unlink()
    return evidence_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--authorization-reference", required=True)
    args = parser.parse_args(argv)
    try:
        evidence_path = release(
            expected_revision=args.expected_revision,
            authorization_reference=args.authorization_reference,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"release failed: {exc}", file=sys.stderr)
        return 1
    print(f"Recovery hold released; evidence={evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
