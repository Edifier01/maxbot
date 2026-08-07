# Decisions

Architecture Memory index for MAX Sender Server. New ADRs go in `docs/adr/` and are listed here.

## Decision Log

| ID | Date | Status | Summary | Link |
|----|------|--------|---------|------|
| ADR-001 | 2026-07-30 | Accepted | Per-tenant campaign worker isolation via RuntimeRegistry + context snapshot | docs/adr/001-tenant-worker-isolation.md |
| ADR-002 | 2026-07-30 | Accepted | Campaign scale pacing (worker/delay/percent roles) | docs/adr/002-campaign-scale-pacing.md |
| ADR-003 | 2026-07-30 | Accepted (phase 1) | Worker module extraction from main.py | docs/adr/003-worker-module-extraction-deferred.md |
| HARNESS-001 | 2026-08-07 | Accepted | Install Cursor AI harness per max-sender-gap.md (selective Agency/ECC/AAS + project-local) | `C:\Users\Maga\Documents\Projects\Global-AI-System\knowledge-catalog\reports\max-sender-gap.md` |
| HARNESS-002 | 2026-08-07 | Accepted | GitHub MCP is required for this project (PR/CI/issues); config in `.cursor/mcp.json`, PAT via env only | `.cursor/mcp.json` |
| REPO-001 | 2026-08-07 | Accepted | Repository is server-only: remove desktop monorepo; flatten former `server/` to root | branch `chore/server-only-repo` |

## When to add an ADR

- Auth/session model changes
- Vault/crypto changes
- Tenant storage topology changes
- Campaign pacing philosophy changes
- Deploy topology changes (e.g. introducing K8s)

Trivial edits: do not create ADRs.
