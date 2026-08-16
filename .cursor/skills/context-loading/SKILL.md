---
name: context-loading
description: Loads MAX Sender project context before planning or implementation. Use when starting work, resuming a task, or deciding whether a change affects desktop, server, or both.
disable-model-invocation: true
---

# Context Loading

## Project Root

Detect the Cursor workspace root, then prefix paths:

| Root looks like | Prefix |
|-----------------|--------|
| This tree: `app/`, `static/`, `.cursor/` at root | none — paths as written |
| Folder containing `server/app/` | `server/` |
| Parent `maxserverapp/` (rare) | `maxserverapp/` or `maxserverapp/server/` as appropriate |

1. Read `README.md` and `AGENTS.md` from the detected project root.
2. Read `.cursor/project-management/CURRENT_CONTEXT.md`, `PROJECT_STATUS.md`, `TASKS.md`, `DECISIONS.md`, and `HANDOFF.md`.
3. Read `README.md` here; `desktop/README.md` only if `desktop/` exists in this workspace.
4. Identify the work zone: `desktop`, `server`, or `both`.
5. Load rules: `max-sender-workspace`, `ai-skills-system`, plus zone rule (`server-workspace` or `desktop-workspace`).
6. Load domain skills for the zone:

| Zone | Skills to read |
|------|----------------|
| `desktop` | `maxserver-static-ui`, `maxserver-campaign`, `maxserver-testing` as relevant |
| `server` | `maxserver-fastapi-backend`, `maxserver-server-deploy`, `maxserver-postgresql`, `maxserver-auth-security`, `maxserver-testing` |
| `both` | all relevant desktop + server skills, then verify desktop/server independence |

7. Load agent docs from `.cursor/agents/README.md` for assigned specialists only.
