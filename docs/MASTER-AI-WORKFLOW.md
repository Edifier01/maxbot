# MASTER AI WORKFLOW - MAX Sender

## Product Analysis
MAX Sender is a Python/FastAPI product for controlled MAX messenger sending. It has a local desktop distribution and a server deployment distribution.

## Domains
- Backend/API: FastAPI routes, worker state, profile/group/message logic.
- Frontend: static HTML/CSS/JS control panel.
- Database: SQLite desktop data, PostgreSQL/server schema, runtime `data/`.
- Security: vault encryption, API PIN, JWT, admin auth, tenant isolation, secrets.
- DevOps: PyInstaller desktop build, Docker/Caddy/Redis/PostgreSQL server stack.
- Campaign domain: pacing, warmup, retry, pause/resume, account safety.

## AI System Layout

```
AGENTS.md                          ← entry point for Cursor
.cursor/
  rules/
    ai-skills-system.mdc           ← always: skill ↔ agent routing
    max-sender-workspace.mdc       ← always: desktop/server split
    server-workspace.mdc           ← server/** globs
  skills/
    context-loading                ← start every session
    start-feature                  ← Feature Plans
    subagent-orchestrator          ← multi-domain routing
    maxserver-server-deploy        ← Docker, VPS, CI/CD
    maxserver-fastapi-backend      ← server/app API
    maxserver-postgresql           ← PG schema, db_pg
    maxserver-auth-security        ← JWT, tenant, secrets
    maxserver-static-ui            ← vanilla HTML/CSS/JS
    maxserver-campaign             ← pacing, warmup, sending safety
    maxserver-testing              ← QA/verifier evidence gate
    maxserver-harness              ← /audit-harness
  agents/                          ← specialist personas
  workflows/feature-lifecycle.md
  commands/                        ← start-feature, deploy-server, improve-ui, ponytail-review, audit-harness
```

External skill library (`skills/`) is a vendored source mirror. Do not load it wholesale; project skills in `.cursor/skills/` are the active distilled layer.

## Workspace Layout

This repo is often opened as the **server tree** (paths as written). If Cursor is opened on a parent folder that contains `server/`, prefix `server/`. A `maxserverapp/` prefix applies only in that older monorepo layout.

## Agent Architecture
Use one root `.cursor/` system for both `desktop/` and `server/`. The orchestrator plans and routes. Specialists work only in scoped areas **and follow their domain skill**. The verifier validates independence, tests, and risks before completion.

## Skills ↔ Agents

| Skill | Agent | Trigger |
|-------|-------|---------|
| `maxserver-server-deploy` | devops-engineer | Docker, deploy, Caddy, CI |
| `maxserver-fastapi-backend` | backend-engineer | API, hooks, worker |
| `maxserver-postgresql` | database-engineer | schema, migrations |
| `maxserver-auth-security` | security-engineer | JWT, tenant, secrets |
| `maxserver-static-ui` | frontend-engineer | static UI |
| `maxserver-campaign` | campaign-specialist | sending safety |
| `maxserver-testing` | qa-engineer, verifier | verification evidence |

## Model Routing Policy
- GPT-5.5: planning, orchestration, documentation, architecture analysis.
- Composer 2.5: routine implementation, tests, repetitive edits.
- Opus: only for high-risk architecture/security/compliance decisions.

## How To Start
Use `/start-feature [task description]`, `/deploy-server` for infra, `/improve-ui` for panels, `/ponytail-review` after a fat diff, `/audit-harness` if skill paths look broken.

See also root `AGENTS.md`.

## Server Deploy Gate
Before any production deploy: pre-deploy checklist in `maxserver-server-deploy`, then `docker compose config`, health check, post-deploy monitoring.
