---
name: maxserver-postgresql
description: MAX Sender hybrid PostgreSQL + per-tenant SQLite, migrations, and backup notes. Use for schema, db_pg.py, or data-path changes.
---

# MAX Sender PostgreSQL

Compose (task-scoped): `postgres-patterns`, `database-migrations`, `backup-hybrid-storage`. This file wins on hybrid layout.

## Layout

| Store | What |
|-------|------|
| PostgreSQL (`app/db_pg.py`, `migrations/`) | SaaS users, subscriptions, admin meta |
| Per-tenant SQLite | Campaign/ops data under `data/tenants/{id}/` |

Do **not** migrate the product to Supabase Auth/PostgREST/Realtime. `postgres-patterns` is indexing/SQL/pooling, not a BaaS rewrite.

## Rules

- Prod DDL: backup first (`scripts/backup-volumes.sh`) — PG volume **and** `max_server_data`.
- Prefer existing migration style in `migrations/`; no Alembic unless a Feature Plan says so.
- Pooling: app connections vs migrate/`pg_dump` (direct) — do not break migrate with transaction-mode-only assumptions.
- Tenant ops data stays in SQLite files; do not “just put it in PG” without an ADR.

## Verify

- Migration applies cleanly; rollback/forward note in the change.
- Relevant DB tests; CI `server-smoke` uses Postgres/`DATABASE_URL`.
