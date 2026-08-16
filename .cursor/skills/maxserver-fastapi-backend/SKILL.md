---
name: maxserver-fastapi-backend
description: MAX Sender FastAPI layout, routes, worker glue, and API change rules. Use when editing app/, main.py, hooks, or HTTP APIs.
---

# MAX Sender FastAPI Backend

Compose (read only what the task needs): `fastapi-patterns`, `python-patterns`. This file wins on layout.

## Layout (this repo)

Workspace root **is** the server tree unless a parent folder contains `server/`.

| Path | Role |
|------|------|
| `main.py` | App entry, lifespan, some worker glue (ADR 003 — further split deferred) |
| `app/main.py` | Server app factory / wiring |
| `app/routes_*.py` | HTTP routes |
| `app/middleware.py` | JWT / tenant context |
| `app/hooks.py` | Worker / campaign hooks |
| `app/config.py` | Settings |
| `docs/HOW-IT-WORKS.md` | Behavior narrative |

Do **not** introduce SQLAlchemy, Alembic, or a greenfield `routers/` tree.

## Rules

- Preserve API compatibility unless a Feature Plan changes it.
- Shared behavior may exist as a desktop copy in the parent monorepo — check `docs/CORE-SYNC.md` if the workspace has `desktop/`.
- Auth, tenant, vault, secrets → also read `maxserver-auth-security` and involve `security-engineer`.
- Campaign send/pacing → `maxserver-campaign`.
- Non-trivial logic: one pytest that fails if the behavior breaks.

## Verify

```powershell
$env:MAX_TEST='1'; $env:MAX_SERVER_MODE='1'; python -m pytest tests/ -q
```
