# AGENTS.md — MAX Sender Server

Multi-tenant FastAPI SaaS for controlled MAX messenger campaigns. AI harness map (keep short).

## Commands

```bash
# Install
pip install -r requirements.txt -r requirements-server.txt
pip install pytest httpx

# Tests (CI smoke)
MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/ -q

# E2E (needs Postgres / DATABASE_URL as in CI)
MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/test_e2e_server.py -q

# Compose validate (set env from .env.example / ci.yml)
docker compose config -q

# Deploy (VPS)
bash scripts/deploy.sh && bash scripts/verify_deploy.sh
bash scripts/backup-volumes.sh
```

## Architecture Pointers

- Product narrative: `docs/HOW-IT-WORKS.md`
- Ops runbook: `docs/PRODUCTION-OPS.md`
- Plan / milestones: `docs/PROJECT_PLAN.md`
- AI workflow: `docs/MASTER-AI-WORKFLOW.md`
- ADRs: `docs/adr/` (index in `.cursor/project-management/DECISIONS.md`)
- Layout: `main.py` (remaining monolith) + `app/` SaaS package; per-tenant SQLite under `data/tenants/{id}/`; SaaS data in PostgreSQL

## Guardrails

- Never weaken tenant isolation (ContextVar + tenant paths) or “optimize away” anti-ban pacing.
- Never commit secrets (`.env`, keys, vault material); treat volume backups as sensitive.
- Do not invent payment/billing gateways — subscriptions are admin-granted.
- Non-trivial work: `/start-feature` → Feature Plan → wait for `proceed` → implement → verifier.
- Prefer skills for procedures; domain agents for high-risk isolation (auth, vault, tenant, campaign, ops).

## Canonical Examples

- Tenant workers: `docs/adr/001-tenant-worker-isolation.md`
- Campaign pacing: `docs/adr/002-campaign-scale-pacing.md`
- Worker extraction: `docs/adr/003-worker-module-extraction-deferred.md`
- Cross-tenant tests: `tests/test_cross_tenant_api.py`, `tests/test_tenant_isolation_sqlite.py`

## Where Things Live

| What | Path |
|------|------|
| Agents | `.cursor/agents/` |
| Skills | `.cursor/skills/` |
| Rules | `.cursor/rules/` |
| Hooks | `.cursor/hooks.json` + `.cursor/hooks/` |
| PM state | `.cursor/project-management/` |
| Workflows | `.cursor/workflows/` |

## MCP

- **GitHub** (required): `.cursor/mcp.json` — set env `GITHUB_PERSONAL_ACCESS_TOKEN` (PAT), then restart Cursor. Used for PRs, checks, issues.
- Other MCP servers: opt-in only; no prod DB MCP by default.

## Feature Entry Point

Use `/start-feature <business goal>` for non-trivial work. Wait for `proceed`.
