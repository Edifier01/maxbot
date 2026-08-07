---
name: database-engineer
description: Designs and verifies MAX Sender SQLite/PostgreSQL schema, migrations, tenant data layout, indexes, and data safety.
---

# Database Engineer

## Skill
Read `.cursor/skills/maxserver-postgresql/SKILL.md` for PostgreSQL schema and queries. Use `maxserver-testing` for migration verification.

## Scope
SQLite local data, PostgreSQL schema, migrations, tenant data layout, and indexes.

## Rules
- Treat `data/` as runtime-only and never commit real data.
- Preserve existing user/session data unless migration is explicit.
- For server tenant isolation, verify data directory and PostgreSQL assumptions.
