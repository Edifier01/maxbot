# MAX Sender — AI Agents

Project-specific agents for coordinated development. **Do not create agents blindly** — add new ones only when the product proves the need.

## Core Agents (always)

| Agent | File | Mode | Role |
|-------|------|------|------|
| **Project Orchestrator** | `project-orchestrator.md` | Readonly | Plans features, assigns specialists, outputs Feature Plans |
| **Verifier** | `verifier.md` | Readonly | Skeptical validation before marking work done |

## Domain Agents

| Agent | File | When to use |
|-------|------|-------------|
| **Backend Engineer** | `backend-engineer.md` | FastAPI, worker, PyMax auth, API endpoints, `main.py`, `antiban_core.py` |
| **Frontend Engineer** | `frontend-engineer.md` | `static/index.html`, admin UI, UX, responsive layout |
| **Database Engineer** | `database-engineer.md` | SQLite schema, `schema_pg.sql`, migrations, indexes |
| **DevOps Engineer** | `devops-engineer.md` | Docker, Caddy, domain, deploy scripts, CI/CD |
| **QA Engineer** | `qa-engineer.md` | Test plans, smoke tests, regression, E2E scenarios |
| **Security Engineer** | `security-engineer.md` | PIN auth, session encryption, secrets, OWASP, public exposure |
| **Campaign Specialist** | `campaign-specialist.md` | Messaging campaigns, antiban, worker pool, send logic |

## Model Routing

| Model | Use for |
|-------|---------|
| GPT-5.5 | Planning, orchestration, research, documentation |
| Composer 2.5 | Implementation, tests, migrations, routine verification |
| Opus | Architecture ADRs, security-critical design, hard tradeoffs |

**Do not use Opus** for routine CRUD, simple UI, or boilerplate.

## How to Start a Feature

```text
/start-feature [describe the business feature]
```

Or invoke `@project-orchestrator` with the feature description. Wait for **Feature Plan approval** before implementation.

## Coordination Rules

1. Read `.cursor/project-management/CURRENT_CONTEXT.md` before work
2. Specialists work within assigned scope only
3. Only the **parent agent** updates project-management files
4. Verifier must run before marking tasks complete
5. For server infra tasks, also read `server/AGENTS.md` and curated skills

## External Skills Library

For server/deployment tasks, curated community skills live in `server/skills-curated/`. See `server/SKILLS.md`. This is **separate** from project skills in `.cursor/skills/`.
