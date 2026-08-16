"""Pytest: project root on import path (standalone server)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def postgres_ready() -> bool:
    if not os.environ.get("DATABASE_URL", "").strip():
        return False
    try:
        import psycopg  # noqa: F401
        import psycopg_pool  # noqa: F401
        return True
    except ImportError:
        return False


requires_postgres = pytest.mark.skipif(
    not postgres_ready(),
    reason="DATABASE_URL and psycopg required (PostgreSQL)",
)
