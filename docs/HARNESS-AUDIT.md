# Harness Audit — MAX Sender Server

**Mode:** Plan vs Reality Review refresh  
**Target:** `C:\Users\Maga\Documents\Projects\server`  
**Generated:** 2026-08-15  
**Previous:** 2026-08-07 (0/7 facades — **obsolete**)  
**Verifier:** [PASS WITH NOTES](e20e90ee-a96c-47d7-9730-bb32a334795c)

---

## 1. Inventory vs bootstrap mandatory core

| Artifact | Present? | Notes |
|----------|----------|-------|
| `AGENTS.md` | **Yes** | Points at facades that now exist |
| `.cursor/agents/project-orchestrator.md` | **Yes** | `readonly: true` |
| `.cursor/agents/verifier.md` | **Yes** | `readonly: true` |
| `.cursor/agents/README.md` | **Yes** | Core 7 + ui-designer wired; extra personas unwired |
| Domain agents | **Partial** | 18 files; routing covers core 7 + orchestrator/verifier/ui-designer |
| `context-loading`, `start-feature`, `subagent-orchestrator` | **Yes** | Root detection (no forced `maxserverapp/` prefix) |
| Domain skills (`maxserver-*`) | **Yes** | 7 facades + `maxserver-harness` + `maxserver-ui-workflow` |
| Generic domain skills | **Yes** | Composed from facades; do not load wholesale |
| `.cursor/skills/README.md` | **Yes** | Index + compose map |
| `.cursor/rules/*.mdc` | **Yes** | Incl. ponytail, delegation gate |
| `.cursor/hooks.json` | **Yes** | |
| `.cursor/mcp.json` | **Yes** | |
| `.cursor/project-management/*` | **Yes** | |
| `.cursor/workflows/feature-lifecycle.md` | **Yes** | |
| `.cursor/commands/` | **Yes** | start-feature, deploy-server, improve-ui, ponytail-review, audit-harness |
| `docs/PROJECT_PLAN.md` | **Yes** | |
| `docs/MASTER-AI-WORKFLOW.md` | **Yes** | |
| `docs/adr/` | **Yes** | 001–007 |
| `skills/` vendored library | **No** | Do not load; not required |
| `knowledge-catalog/` | **Yes** | `sources.json` + this gap report |

**Coverage:** shell + domain facades **operational**. Remaining harness gap = extra-agent P1 (do not expand roster without `/audit-harness`).

---

## 2. Quality issues

### Critical

None. Facade paths exist on disk.

### High

1. **Agent roster bloat vs routing** — extra files (`appsec-engineer`, `identity-access`, `backend-architect`, `database-reliability`, `devops-automator`, `api-tester`, `campaign-antiban`, `secrets-credential`) still unwired. Intentional until a Feature Plan wires or merges them. Do not claim P1 roster expansion done.

### Medium

2. **Path prefix** — some older docs still say `maxserverapp/`; `context-loading` now detects server-as-root.
3. **`desktop-workspace.mdc`** — N/A when this tree is the Cursor root.
4. **No vendored `skills/`** — AGENTS.md must not claim a root library exists.

### Good (keep)

- `/start-feature` + specialist-delegation proceed gate
- Readonly orchestrator/verifier
- Mechanical commands
- Secret-scan hooks
- Knowlange DX: `/ponytail-review`, `/audit-harness`, NameThatUI lookup — no Railway/Supabase/n8n

---

## 3. Agent ↔ skill wiring

| Agent | Skill | On disk? |
|-------|-------|----------|
| backend-engineer | `maxserver-fastapi-backend` | **Yes** |
| frontend-engineer | `maxserver-static-ui` | **Yes** |
| ui-designer | `maxserver-ui-workflow` | **Yes** |
| database-engineer | `maxserver-postgresql` | **Yes** |
| devops-engineer | `maxserver-server-deploy` | **Yes** |
| security-engineer | `maxserver-auth-security` | **Yes** |
| campaign-specialist | `maxserver-campaign` | **Yes** |
| qa-engineer / verifier | `maxserver-testing` | **Yes** |

Facades compose generics (see `.cursor/skills/README.md`). Load facade first.

---

## 4. Verdict

Harness is **operational**. The 2026-08-07 “0% domain skill layer” finding is closed (2026-08-15 facades). Remaining work is optional roster hygiene, not a blocker.

---

## Related

- Gap report: `knowledge-catalog/reports/max-sender-gap.md`
- Knowlange index: `knowledge-catalog/sources.json`
- Codebase audit: `docs/CODEBASE-AUDIT.md` (product snapshot 2026-08-07; not re-run this pass)
