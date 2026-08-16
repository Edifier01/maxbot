# MAX Sender Agents

Use the smallest useful agent set. The orchestrator plans, specialists perform scoped work (following their skill), and the verifier checks before completion.

Routing: `.cursor/rules/ai-skills-system.mdc`

## Core Agents
- `project-orchestrator.md`: planning, routing, Feature Plans. Readonly by default.
- `verifier.md`: skeptical validation. Readonly by default.

## Specialist Agents

| Agent | Skill | Scope |
|-------|-------|-------|
| `backend-engineer.md` | `maxserver-fastapi-backend` | FastAPI, worker, API, shared core |
| `frontend-engineer.md` | `maxserver-static-ui` | static HTML/CSS/JS UI |
| `ui-designer.md` | `maxserver-ui-workflow`, `web-design-guidelines`, `ui-ux-pro-max` | UI audit, design brief (readonly) |
| `database-engineer.md` | `maxserver-postgresql` | SQLite/PostgreSQL schema, isolation |
| `qa-engineer.md` | `maxserver-testing` + deploy checklist | smoke, regression, deploy verify |
| `devops-engineer.md` | `maxserver-server-deploy` | Docker, Caddy, CI/CD, deployment |
| `security-engineer.md` | `maxserver-auth-security` | vault, JWT, PIN, secrets, tenant |
| `campaign-specialist.md` | `maxserver-campaign` | MAX sending, pacing, session safety |

## Orchestration Skills
- `context-loading` — every session start
- `start-feature` — Feature Plans
- `subagent-orchestrator` — multi-domain work
- `maxserver-harness` — `/audit-harness` only; do not grow this roster without a routing row
