"""db_pg pool API smoke (без реального PostgreSQL)."""

from __future__ import annotations

from app import db_pg


def test_db_pg_pool_not_open_before_use():
    db_pg.close()
    assert db_pg._pool is None
    db_pg._self_check()
