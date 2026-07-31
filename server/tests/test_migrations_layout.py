"""P2: layout миграций и bootstrap schema."""

from __future__ import annotations

from pathlib import Path


def test_schema_and_migrations_exist():
    base = Path(__file__).resolve().parents[1]
    assert (base / "schema_pg.sql").is_file()
    assert (base / "migrations" / "001_saas_core.sql").is_file()
    assert (base / "migrations" / "002_revoked_tokens.sql").is_file()
    assert (base / "migrations" / "003_tenant_token_version.sql").is_file()
    legacy_path = base / "docs" / "archive" / "schema_pg_legacy.sql"
    assert legacy_path.is_file()
    bootstrap = (base / "schema_pg.sql").read_text(encoding="utf-8")
    assert "schema_migrations" in bootstrap
    saas = (base / "migrations" / "001_saas_core.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS tenants" in saas
    legacy = legacy_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS profiles" in legacy
