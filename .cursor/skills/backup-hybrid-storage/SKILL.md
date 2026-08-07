---
name: backup-hybrid-storage
description: Backup and restore discipline for MAX Sender hybrid PostgreSQL volume plus max_server_data (SQLite/sessions). Use for backup scripts, DR, or data-path changes.
---

# Backup Hybrid Storage

## Purpose

Ensure both SaaS PG and per-tenant filesystem data are recoverable.

## When To Use

- Changing `scripts/backup-volumes.sh`, `restore-volumes.sh`, volumes in compose, tenant data layout

## Workflow

1. Read `docs/PRODUCTION-OPS.md` backup/restore sections.
2. Backup must cover PG volume **and** `max_server_data` (SQLite + sessions/keys).
3. Prefer tested restore (`restore-volumes.sh`) over untested archives.
4. Treat backups as sensitive (vault material).
5. Coordinate with `database-reliability` and `devops-automator`.

## Validation Checklist

- [ ] Both stores covered
- [ ] Restore steps documented/tested
- [ ] Secrets not copied into git

## Related Agents

- `database-reliability`, `devops-automator`, `secrets-credential`
