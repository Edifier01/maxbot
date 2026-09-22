# T28 migration evidence and runbook boundary

Status: `PARTIAL` for source review; no production migration was authorized or
executed in this remediation run. No production schema migration was run.

## Current schema paths

- PostgreSQL bootstrap is `schema_pg.sql`; ordered migrations live in
  `migrations/*.sql` and are applied by the existing migration runner.
- Applied PostgreSQL migration hashes are retained; changing an applied SQL
  file must fail with a checksum mismatch. New PostgreSQL changes require a new
  additive migration.
- SQLite additions from this run are idempotent `CREATE TABLE IF NOT EXISTS`
  and guarded column/index additions in `app/sqlite_backend.py`. Existing
  `message_pool`, `send_log`, profiles, groups, sessions, and settings are not
  deleted or reset.

## Safe sequence

1. Inventory every global/tenant SQLite database and PostgreSQL schema.
2. Create and verify a coordinated encrypted backup outside Git.
3. Run an isolated restore rehearsal and record counts/invariants.
4. Apply additive schema changes in a disposable fixture first.
5. Rerun the migration; the second run must be a no-op and preserve history.
6. Keep an explicit recovery hold before any action-capable runtime starts.

No `down -v`, volume deletion, reset, or live/provider migration was run here.
The current checks prove source-level idempotent declarations and fixture
behavior only; they do not prove a production restore.
