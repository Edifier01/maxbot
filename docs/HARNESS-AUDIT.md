# Harness Audit — MAX Sender Server

**Mode:** `/audit-project` phase 2 (refreshed)  
**Target:** `C:\Users\Maga\Documents\Projects\server`  
**Generated:** 2026-08-07 (evening refresh)  
**Baseline:** bootstrap mandatory core + on-disk harness inventory  

---

## 1. Inventory vs bootstrap mandatory core

| Artifact | Bootstrap expectation | Present? | Notes |
|----------|----------------------|----------|-------|
| `AGENTS.md` | Mandatory | **Yes** | Entry map; references missing `maxserver-*` skills |
| `.cursor/agents/project-orchestrator.md` | Mandatory | **Yes** | `readonly: true` |
| `.cursor/agents/verifier.md` | Mandatory | **Yes** | `readonly: true`; references missing skills |
| `.cursor/agents/README.md` | Expected | **Yes** | Lists 7 specialists; 11 extra agents unwired |
| Domain agents | Quality-driven | **Partial** | 18 total; routing table covers 7 only |
| `.cursor/skills/context-loading/` | Mandatory | **Yes** | References missing `maxserver-*` paths |
| `.cursor/skills/start-feature/` | Mandatory | **Yes** | Feature Plan template present |
| `.cursor/skills/subagent-orchestrator/` | Mandatory | **Yes** | Multi-domain routing |
| Domain skills (`maxserver-*`) | Required for this product | **No** | **0/7 on disk** — critical break |
| Generic domain skills | Optional fallback | **Yes** | 15 skills (fastapi-patterns, tenant-isolation-max, …) |
| `.cursor/skills/README.md` | Expected index | **No** | Referenced in `ai-skills-system.mdc` |
| `.cursor/rules/*.mdc` | Thin always/glob rules | **Yes** | 14 rules (incl. ponytail, delegation gate) |
| `.cursor/hooks.json` | Optional | **Yes** | Secret-scan + CI-weakening warnings |
| `.cursor/mcp.json` | Optional | **Yes** | Present |
| `.cursor/project-management/*` | Mandatory | **Yes** | CONTEXT, TASKS, DECISIONS, HANDOFF, fix plans |
| `.cursor/workflows/feature-lifecycle.md` | Mandatory | **Yes** | Proceed gate + domain gates |
| `.cursor/commands/` | Expected | **Yes** | start-feature, deploy-server |
| `docs/PROJECT_PLAN.md` | Mandatory | **Yes** | |
| `docs/MASTER-AI-WORKFLOW.md` | Mandatory | **Yes** | References missing skills |
| `docs/adr/` | Phase 1 memory | **Yes** | 001–003 |
| `skills/` vendored library | Referenced in AGENTS | **No** | Not on disk in this workspace |
| `knowledge-catalog/` | Meta audit output | **No** | Created by this audit run |

**Coverage estimate:** mandatory core shell ~**85%** installed; **domain skill layer 0%** (broken references).

---

## 2. Quality issues

### Critical

1. **Broken skill routing** — `AGENTS.md`, `ai-skills-system.mdc`, every specialist agent, `context-loading`, `feature-lifecycle`, and `verifier` point at seven `maxserver-*` skill paths that **do not exist**. Agents instructed to read skills will fail silently or skip checklists.

### High

2. **Agent roster bloat vs routing** — 18 agent files; `ai-skills-system.mdc` and `agents/README.md` wire only 7. Extra personas (`appsec-engineer`, `identity-access`, `backend-architect`, `database-reliability`, `devops-automator`, `api-tester`, `campaign-antiban`, `secrets-credential`) have no routing table entries.
3. **Stale audit docs** — earlier `docs/CODEBASE-AUDIT.md` / this file claimed harness absent; harness was added since then.
4. **Path prefix drift** — multiple files reference `maxserverapp/` canonical root while workspace **is** `server/`; `server-workspace.mdc` globs `{server/**,maxserverapp/server/**}`.

### Medium

5. **Missing skills index** — `.cursor/skills/README.md` referenced but absent.
6. **Dual naming** — on-disk skills use generic names (`fastapi-patterns`); harness docs use product names (`maxserver-fastapi-backend`); no mapping file bridges them.
7. **desktop-workspace rule** — present but `desktop/` folder not in this workspace (server-only root).
8. **Vendored `skills/` library** — AGENTS.md says do not load wholesale; directory absent here.

### Good (keep)

- Proceed gate via `/start-feature` + `specialist-delegation.mdc`
- Verifier + orchestrator marked readonly
- Mechanical commands in `mechanical-commands.mdc`
- Security hooks (secret pattern detection, sensitive file read warning)
- PM state populated (fix plans marked done, DECISIONS indexed)
- Product docs strong — harness should link, not replace

---

## 3. Agent ↔ skill wiring (current)

| Agent | Declared skill path | Skill exists? |
|-------|---------------------|---------------|
| backend-engineer | `maxserver-fastapi-backend` | **No** |
| frontend-engineer | `maxserver-static-ui` | **No** |
| database-engineer | `maxserver-postgresql` | **No** |
| devops-engineer | `maxserver-server-deploy` | **No** |
| security-engineer | `maxserver-auth-security` | **No** |
| campaign-specialist | `maxserver-campaign` | **No** |
| qa-engineer / verifier | `maxserver-testing` | **No** |
| (unwired extras) | various / none | partial generic skills exist |

Nearest on-disk substitutes: `fastapi-patterns`, `postgres-patterns`+`database-migrations`, `deployment-patterns`+`docker-patterns`, `security-review`+`tenant-isolation-max`+`vault-fernet-sessions`, `antiban-campaign-safety`, `python-testing`.

---

## 4. Harness audit verdict

Bootstrap **shell is present** but **not operational** until the seven `maxserver-*` project skills are created (distilled wrappers) **or** all routing/docs are rewritten to the 18 generic skill names. Prefer **Add** distilled `maxserver-*` skills that compose existing generic skills + MAX Sender paths/checklists — smallest change to 20+ referencing files.

---

## Related

- Codebase audit: `docs/CODEBASE-AUDIT.md`
- Gap Report: `knowledge-catalog/reports/max-sender-gap.md`
