from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from app import db_pg


class _Cursor:
    def __init__(self):
        self.calls = []
        self.row = None

    def execute(self, sql, params=()):
        self.calls.append((" ".join(sql.split()), params))
        if "SELECT tenant_id FROM onboarding_invite_tenants" in sql:
            self.row = {"tenant_id": 42}

    def fetchone(self):
        return self.row


def test_onboarding_invite_locator_is_additive_pg_migration_and_expiring(tmp_path, monkeypatch):
    base = Path(__file__).resolve().parents[1]
    migration = base / "migrations" / "004_onboarding_invite_tenants.sql"
    assert migration.is_file()
    sql = migration.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS onboarding_invite_tenants" in sql
    assert "REFERENCES tenants(id) ON DELETE CASCADE" in sql
    assert "expires_at" in sql

    cursor = _Cursor()

    @contextmanager
    def fake_cursor(*, transaction=False):
        yield cursor

    monkeypatch.setattr(db_pg, "_cursor", fake_cursor)
    db_pg.register_onboarding_invite("a" * 64, 42, "2026-10-01T00:00:00+00:00")
    assert db_pg.get_onboarding_invite_tenant("a" * 64) == 42
    assert any("INSERT INTO onboarding_invite_tenants" in call[0] for call in cursor.calls)
    assert any("expires_at > NOW()" in call[0] for call in cursor.calls)
