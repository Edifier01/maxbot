-- Bootstrap PostgreSQL для MAX Sender (server mode).
-- SaaS DDL — migrations/001_saas_core.sql
-- Legacy SQLite mirror (не используется runtime) — schema_pg_legacy.sql

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);
