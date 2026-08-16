# MAX Sender Project Skills

Active skills live here. Do **not** load `skills/` or `Knowlange/` wholesale at runtime.

When a `maxserver-*` facade exists, load it first. Generics (`fastapi-patterns`, …) are composed from the facade — do not load the whole generic unless the facade says so.

## Orchestration

| Skill | Role |
|-------|------|
| `context-loading` | Session start, zone, path prefix |
| `start-feature` | Feature Plan |
| `subagent-orchestrator` | Multi-domain Task routing |
| `maxserver-harness` | `/audit-harness` — agents/skills/approvals (not a new runtime) |

## Domain facades (`maxserver-*`)

| Skill | Agent | Composes |
|-------|-------|----------|
| `maxserver-fastapi-backend` | backend-engineer | `fastapi-patterns`, `python-patterns` |
| `maxserver-postgresql` | database-engineer | `postgres-patterns`, `database-migrations`, `backup-hybrid-storage` |
| `maxserver-server-deploy` | devops-engineer | `deployment-patterns`, `docker-patterns`, `redis-patterns` |
| `maxserver-auth-security` | security-engineer | `security-review`, `tenant-isolation-max`, `vault-fernet-sessions`, `saas-multi-tenant` |
| `maxserver-campaign` | campaign-specialist | `antiban-campaign-safety`, `celery-parity` |
| `maxserver-testing` | qa-engineer, verifier | `python-testing` (ignore 80% coverage dogma) |
| `maxserver-static-ui` | frontend-engineer | project constraints |

## UI improvement (Knowlange-derived)

| Skill | Source | Role |
|-------|--------|------|
| `maxserver-ui-workflow` | project | Pipeline: audit → brief → implement → verify; NameThatUI lookup |
| `ui-ux-pro-max` | [agentic-awesome-skills](file:///C:/Users/Maga/Documents/Projects/Knowlange/agentic-awesome-skills-main/skills/ui-ux-pro-max) | Design system search CLI + UX CSVs |
| `web-design-guidelines` | [vercel-labs/agent-skills](https://www.skills.sh/vercel-labs/agent-skills/web-design-guidelines) | Vercel Web Interface Guidelines audit |
| `frontend-design-max` | adapted from `frontend-design` | Visual direction brief |
| `maxserver-static-ui` | project | Vanilla panel constraints + tokens |

**CLI (from repo root):**

```powershell
$env:PYTHONIOENCODING='utf-8'
python .cursor/skills/ui-ux-pro-max/scripts/search.py "SaaS dashboard admin dark" --design-system -p "MAX Sender" -f markdown
```

## Commands

- `/start-feature` — Feature Plan
- `/improve-ui [scope]` — UI audit + brief
- `/deploy-server` — deploy checklist
- `/ponytail-review` — overengineering on current diff
- `/audit-harness` — agents/skills path check

External library path (reference only): `C:\Users\Maga\Documents\Projects\Knowlange\agentic-awesome-skills-main\`
