# MAX Sender Server — Agents

Use the smallest useful agent set. Orchestrator plans (readonly), specialists execute scoped work, verifier gates completion.

Routing: `.cursor/rules/ai-skills-system.mdc`  
Skills map: `.cursor/skills/SKILLS-INVENTORY.md`  
Model policy: `docs/MASTER-AI-WORKFLOW.md`

## Core Agents

| Agent | Model | Readonly | Role |
|-------|-------|----------|------|
| `project-orchestrator` | GPT-5.5 | yes | Feature Plans, routing, PM updates |
| `verifier` | Composer 2.5 | yes | PASSED / FAILED gate |

## Specialist Agents

| Agent | Model | Skill | Scope |
|-------|-------|-------|-------|
| `backend-engineer` | Composer 2.5 | `maxserver-fastapi-backend` | FastAPI, worker, API |
| `frontend-engineer` | Composer 2.5 | `maxserver-static-ui` | `static/` |
| `database-engineer` | Composer 2.5 | `maxserver-postgresql` | PG + tenant SQLite |
| `security-engineer` | Opus | `maxserver-auth-security` | JWT, vault, tenant |
| `devops-engineer` | Composer 2.5 | `maxserver-server-deploy` | Docker, Caddy, CI |
| `campaign-specialist` | Composer 2.5 | `maxserver-campaign` | Pacing, sending safety |
| `qa-engineer` | Composer 2.5 | `maxserver-testing` | Smoke, regression, deploy verify |

## Orchestration Skills

- `context-loading` — every session start
- `start-feature` — Feature Plans + `proceed` gate
- `subagent-orchestrator` — multi-domain execution after approval

## Coordination Rules

- Specialists **must not** edit `.cursor/project-management/*`.
- Parent agent owns integration, collision resolution, PM updates.
- Parallel agents **must not** edit the same file in the same round.
- Tasks marked COMPLETED only after verifier PASSED.

## Start Work

```text
/start-feature [business feature]
```

Wait for `proceed` before implementation.
