---
name: context-loading
description: Load MAX Sender project context before any agent work. Read project-management files and relevant docs.
---

# Context Loading — MAX Sender

Load project context **before** planning or implementing any feature.

## Required Reads (always)

1. `.cursor/project-management/CURRENT_CONTEXT.md` — active focus, architecture
2. `.cursor/project-management/PROJECT_STATUS.md` — what's done / in progress
3. `.cursor/project-management/TASKS.md` — backlog priorities

## Conditional Reads

| If working on… | Also read |
|----------------|-----------|
| Backend / API | `AUDIT.md` (API section), `README.md` |
| Server / deploy | `server/README.md`, `server/AGENTS.md` |
| UI | `static/index.html`, `AUDIT.md` (UI section) |
| Security | `AUDIT.md` (security), `README.md` (security table) |
| Database | `AUDIT.md` (schema), `schema_pg.sql` |
| Architecture decision | `.cursor/project-management/DECISIONS.md` |

## Session Handoff

If continuing previous work, read:
- `.cursor/project-management/HANDOFF.md`

## Agent Index

- `.cursor/agents/README.md` — which agent to use

## Do Not Load

- Entire `server/skills/` library (~1900 skills)
- Full `main.py` unless backend task (read relevant sections only)
- `venv/`, `dist/`, `data/` session contents

## Quick Architecture Reminder

```
Local:  run.bat → main.py → 127.0.0.1:8765 → static/index.html
Server: docker compose → server/app/main.py → Caddy HTTPS → same UI
Data:   data/app.db (SQLite) + data/sessions/ (encrypted)
```

## After Loading

State internally:
- What mode (local / server / both)?
- What entities are affected?
- Security implications?

Then proceed with assigned task or Feature Plan.
