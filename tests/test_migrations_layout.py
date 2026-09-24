"""P2: layout миграций и bootstrap schema."""

from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
import hashlib

import pytest

from app import db_pg


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


class _MigrationCursor:
    def __init__(self):
        self.checksums = {}
        self.row = None

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT pg_advisory_xact_lock"):
            return self
        if normalized.startswith("SELECT checksum FROM schema_migrations"):
            self.row = (
                {"checksum": self.checksums[params[0]]}
                if params[0] in self.checksums
                else None
            )
            return self
        if normalized.startswith(
            "INSERT INTO schema_migrations (version) VALUES ('"
        ):
            version = normalized.split("VALUES ('", 1)[1].split("'", 1)[0]
            self.checksums.setdefault(version, None)
            return self
        if normalized.startswith("INSERT INTO schema_migrations"):
            if "ON CONFLICT" not in normalized or params[0] not in self.checksums:
                self.checksums[params[0]] = params[1] if params else None
            elif "DO UPDATE" in normalized and self.checksums[params[0]] is None:
                self.checksums[params[0]] = params[1]
            return self
        if normalized.startswith("UPDATE schema_migrations SET checksum"):
            version = params[1]
            if self.checksums.get(version) is None:
                self.checksums[version] = params[0]
            return self
        return self

    def fetchone(self):
        return self.row


def test_new_migration_checksum_is_recorded_in_first_apply(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    migration = migrations / "001_sample.sql"
    migration.write_text(
        "INSERT INTO schema_migrations (version) VALUES ('001_sample') "
        "ON CONFLICT DO NOTHING;\nCREATE TABLE sample (id INTEGER);\n",
        encoding="utf-8",
    )
    cursor = _MigrationCursor()

    @contextmanager
    def fake_cursor(*, transaction=False):
        assert transaction is True
        yield cursor

    monkeypatch.setattr(db_pg, "_schema_dir", lambda: tmp_path)
    monkeypatch.setattr(db_pg, "_cursor", fake_cursor)

    db_pg._apply_pending_migrations()

    expected = hashlib.sha256(migration.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    assert cursor.checksums["001_sample"] == expected

    migration.write_text(migration.read_text(encoding="utf-8") + "-- changed\n")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        db_pg._apply_pending_migrations()
