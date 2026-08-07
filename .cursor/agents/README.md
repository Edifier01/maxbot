# Agents — MAX Sender Server

| Agent | Role | Model tier | Readonly |
|-------|------|------------|----------|
| `project-orchestrator` | Feature Plans, routing | Plan (Grok) | yes |
| `verifier` | Evidence-based completion gate | Implement (Composer) | yes |
| `backend-architect` | Module boundaries, `main.py` extraction | Plan / Deep when justified | no |
| `identity-access` | JWT, sessions, impersonation, rate limit | Implement / Deep for auth design | no |
| `appsec-engineer` | AuthZ, tenant leak, admin surfaces | Deep when threat-model | no |
| `secrets-credential` | Vault, `.env`, volume secrets | Implement / Deep | no |
| `devops-automator` | Docker, Caddy, CI/CD, scripts | Implement / Plan for ops design | no |
| `database-reliability` | PG + SQLite hybrid, migrations, backup | Implement | no |
| `api-tester` | pytest/httpx/e2e alignment with CI | Implement | no |
| `campaign-antiban` | Campaign engine, pacing, MAX API safety | Implement / Deep for pacing changes | no |

## Considered but NOT created

- Full Agency/ECC reviewer rosters (overlap with verifier + appsec)
- Agency `security-architect` — optional Feature-Plan-only deep escalate
- ECC `fastapi-reviewer` / `security-reviewer` — optional second opinion
- Payments / billing agents — product N/A
- Heavy frontend / SPA agents — static HTML panel only

## Skill mapping (intentional subsets)

See each agent file. Parent may use `context-loading`, `start-feature`, `subagent-orchestrator`. Never assign all skills to all agents.
