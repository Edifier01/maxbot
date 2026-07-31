"""Временный tenant context + SQLite conn для admin API (P3)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import sqlite3

from app.tenant import tenant_scope
from app.runtime import main as app_main


@contextmanager
def tenant_conn(
    tenant_id: int,
    *,
    use_global_data: bool = False,
) -> Iterator[sqlite3.Connection]:
    """Переключить tenant, вернуть conn; восстановить контекст middleware."""
    with tenant_scope(tenant_id=tenant_id, role="admin", use_global_data=use_global_data):

        with app_main._conn() as conn:
            yield conn
