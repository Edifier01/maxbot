# MASTER AI WORKFLOW — MAX Sender Server

## Product

MAX Sender Server — Python/FastAPI multi-tenant SaaS для controlled MAX messenger sending на VPS (Docker, Caddy, PostgreSQL).

Plan: `docs/PROJECT_PLAN.md`  
Bootstrap source: `ai-agent-system-bootstrap/`

## Domains

- **Backend/API**: `main.py`, `app/routes_*.py`, worker pool
- **Frontend**: `static/` (vanilla HTML/CSS/JS)
- **Database**: PostgreSQL (SaaS) + SQLite per tenant (ops)
- **Security**: vault, JWT, tenant isolation, secrets
- **Campaign**: antiban, warmup, pacing, pause/resume
- **DevOps**: Docker, Caddy, Redis, CI/CD

## AI System Layout

```
AGENTS.md
docs/PROJECT_PLAN.md
docs/MASTER-AI-WORKFLOW.md          ← this file
.cursor/
  agents/                           ← orchestrator, verifier, specialists
  skills/                           ← context-loading, start-feature, domain skills
  skills/SKILLS-INVENTORY.md
  workflows/feature-lifecycle.md
  project-management/               ← operational state
  commands/start-feature.md
  rules/ai-skills-system.mdc
```

## Model Routing

| Model | Slug | Use for |
|-------|------|---------|
| Composer 2.5 | `composer-2.5-fast` | implementation, CRUD, UI, tests, migrations, verifier |
| GPT-5.5 | `gpt-5.5-medium` | planning, orchestration, docs, deploy planning |
| Opus | `claude-opus-4-8-thinking-high` | security architecture, high-risk auth/tenant design |

### Default Agent Models

| Agent | Model |
|-------|-------|
| project-orchestrator | GPT-5.5 |
| verifier | Composer 2.5 |
| backend/frontend/database/devops/campaign/qa | Composer 2.5 |
| security-engineer | Opus |

### Escalation

Composer → GPT-5.5/Opus when: repeated failures, cross-module architecture, auth/tenant/vault changes, campaign safety at scale.

### Downgrade

After planning/review, routine implementation back to Composer 2.5.

## Agent Architecture

```
User: /start-feature [goal]
  → context-loading
  → project-orchestrator (Feature Plan + Model Strategy)
  → user: proceed
  → subagent-orchestrator (Mission Brief, scoped rounds)
  → specialists (Composer 2.5 / Opus for security)
  → verifier (PASSED | FAILED)
  → parent updates PM state
```

## Skills ↔ Agents

See `.cursor/skills/SKILLS-INVENTORY.md`.

| Skill | Agent |
|-------|-------|
| `maxserver-server-deploy` | devops-engineer |
| `maxserver-fastapi-backend` | backend-engineer |
| `maxserver-postgresql` | database-engineer |
| `maxserver-auth-security` | security-engineer |
| `maxserver-static-ui` | frontend-engineer |
| `maxserver-campaign` | campaign-specialist |
| `maxserver-testing` | qa-engineer, verifier |

## Agent Coordination

- Define file ownership before parallel work.
- No two agents edit the same file in one round.
- Specialists do not edit `.cursor/project-management/*`.
- COMPLETED only after verifier PASSED.

## How To Start

```text
/start-feature [business feature]
```

Wait for `proceed` before implementation.

Deploy infra: `/deploy-server [change]`

## Server Deploy Gate

Pre-deploy: `maxserver-server-deploy` checklist → `docker compose config` → health → post-deploy monitoring (`docs/PRODUCTION-OPS.md`).
