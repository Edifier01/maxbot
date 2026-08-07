# Gap Report — MAX Sender Server

**Mode:** `/audit-project` phase 4  
**Target:** `C:\Users\Maga\Documents\Projects\server`  
**Generated:** 2026-08-07  
**Author:** project-architect + knowledge-librarian  

---

## Executive summary

The MAX Sender **server** tree has a mature product codebase and a **mostly installed** AI harness shell. The harness is **not operational** because every routing document points at seven `maxserver-*` project skills that **do not exist on disk**, while eighteen generic skills (`fastapi-patterns`, `tenant-isolation-max`, …) sit unwired.

**Recommended fix (Option A — smallest diff):** Add seven thin `maxserver-*` facade skills that compose existing generics + product doc pointers. Wire eight extra agents into `ai-skills-system.mdc`. Add `.cursor/skills/README.md`. Do **not** rewrite 20+ files to generic names.

---

## SOURCE COVERAGE

| Source | Location | Status | Used for |
|--------|----------|--------|----------|
| Product README | `README.md` | ✓ | deploy quickstart |
| Architecture narrative | `docs/HOW-IT-WORKS.md` | ✓ | domain map |
| Ops runbook | `docs/PRODUCTION-OPS.md` | ✓ | deploy/backup gates |
| Product plan | `docs/PROJECT_PLAN.md` | ✓ | scope/out-of-scope |
| ADRs 001–003 | `docs/adr/` | ✓ | workers, pacing, main.py |
| Core sync | `docs/CORE-SYNC.md` | ✓ | desktop/server parity |
| CI workflows | `.github/workflows/` | ✓ | mechanical commands |
| Test suite | `tests/` (32 files) | ✓ | verifier evidence |
| Orchestration skills | context-loading, start-feature, subagent-orchestrator | ✓ | session + Feature Plan |
| Generic domain skills | 15 skills in `.cursor/skills/` | ✓ partial | ECC-derived patterns |
| **maxserver-* skills** | `.cursor/skills/maxserver-*/` | **✗ missing** | all agent routing |
| Static UI skill coverage | — | **✗ gap** | no frontend skill on disk |
| Testing skill (project) | python-testing only | partial | no MAX_TEST/CI checklist skill |
| Vendored `skills/` library | repo root | **✗ absent** | AGENTS.md references it |
| `knowledge-catalog/sources.json` | meta | **✗ absent** | external source index |
| Global-AI-System bootstrap | external | **✗ absent on machine** | baseline spec |
| Agency/AAS/ECC upstream | user machine (unindexed) | unknown | not wired via sources.json |

---

## KEEP

### Product docs (link from AGENTS.md — do not replace)
- `README.md`
- `docs/HOW-IT-WORKS.md`
- `docs/PRODUCTION-OPS.md`
- `docs/PROJECT_PLAN.md`
- `docs/adr/001-tenant-worker-isolation.md`
- `docs/adr/002-campaign-scale-pacing.md`
- `docs/adr/003-worker-module-extraction-deferred.md`
- `docs/CORE-SYNC.md`

### Harness shell (working structure)
- `AGENTS.md` — entry point (update after skill fix)
- `docs/MASTER-AI-WORKFLOW.md`
- `.cursor/agents/project-orchestrator.md` (readonly)
- `.cursor/agents/verifier.md` (readonly)
- `.cursor/skills/context-loading/`, `start-feature/`, `subagent-orchestrator/`
- `.cursor/rules/` — especially `ai-skills-system.mdc`, `specialist-delegation.mdc`, `mechanical-commands.mdc`, `max-sender-workspace.mdc`, `server-workspace.mdc`, `tenant-isolation.mdc`, `vault-secrets.mdc`, `antiban-safety.mdc`, `ponytail.mdc`
- `.cursor/hooks.json` + hook scripts (secret scan, CI protection)
- `.cursor/project-management/` — CURRENT_CONTEXT, TASKS, DECISIONS, HANDOFF
- `.cursor/workflows/feature-lifecycle.md`
- `.cursor/commands/start-feature.md`, `deploy-server.md`

### Core specialist agents (7 — already in routing table)
- `backend-engineer`, `frontend-engineer`, `database-engineer`
- `devops-engineer`, `security-engineer`, `campaign-specialist`, `qa-engineer`

### Generic on-disk skills (compose into maxserver-* facades)
| Skill | Role |
|-------|------|
| `fastapi-patterns` | Backend patterns (adapt note present) |
| `postgres-patterns` + `database-migrations` | PG layer |
| `deployment-patterns` + `docker-patterns` + `backup-hybrid-storage` | Deploy/ops |
| `security-review` + `tenant-isolation-max` + `vault-fernet-sessions` + `saas-multi-tenant` | Auth/security |
| `antiban-campaign-safety` + `celery-parity` | Campaign |
| `python-testing` | Test patterns (needs project checklist wrapper) |
| `redis-patterns` | Auth rate limit / Redis health |

### Extra agents — Keep + Wire
| Agent | Wire to | Rationale |
|-------|---------|-----------|
| `secrets-credential` | vault-fernet-sessions + maxserver-auth-security | Already uses real skill paths |
| `appsec-engineer` | maxserver-auth-security + security-review | Threat model / AuthZ reviews |
| `identity-access` | maxserver-auth-security | JWT/session/impersonation isolation |
| `campaign-antiban` | maxserver-campaign + antiban-campaign-safety | Stronger than generic campaign-specialist for pacing |
| `backend-architect` | maxserver-fastapi-backend | main.py extraction / module boundaries (ADR 003) |

---

## REPLACE

| Item | Replace with | Reason |
|------|--------------|--------|
| Broken `maxserver-*` references (0 files) | Seven new facade SKILL.md files | Restore agent skill loading without rewriting all agents |
| Stale `docs/CODEBASE-AUDIT.md` harness section | Updated inventory (done in refresh) | Said harness absent |
| Stale `docs/HARNESS-AUDIT.md` | Refreshed audit (done) | Said 0% installed |
| `maxserverapp/` path prefix in context-loading | Detect workspace root: if `server/` is root, skip prefix | Server-only workspace confusion |
| AGENTS.md "External Skills Library in skills/" | Point to `.cursor/skills/` only; note vendored lib optional/deferred | Directory absent |

---

## REMOVE (or merge — do not delete working agents without wiring replacement)

| Item | Action | Reason |
|------|--------|--------|
| `devops-automator` | **Merge → devops-engineer** | Duplicate DevOps persona; routing has one slot |
| `api-tester` | **Merge → qa-engineer** or demote to doc section | Overlap with qa-engineer + python-testing |
| `database-reliability` | **Merge → database-engineer** | Hybrid backup/pooling fits database-engineer scope |
| Claim of vendored root `skills/` in docs | **Remove false claim** until library is actually vendored |
| `desktop-workspace.mdc` always-on confusion | **Keep rule** but add note: N/A when workspace is server-only root | Harmless glob; optional clarify in AGENTS |

**Do NOT remove:** campaign-specialist (keep alongside campaign-antiban with distinct scopes), backend-architect (needed for ADR 003 work).

---

## ADD (priority order)

### P0 — Unblocks all agents
1. **`.cursor/skills/maxserver-fastapi-backend/SKILL.md`** — Module map: `main.py`, `app/routes_*`, worker glue; read `fastapi-patterns`; MAX Sender layout overrides; mechanical: pytest smoke paths.
2. **`.cursor/skills/maxserver-auth-security/SKILL.md`** — Compose `security-review`, `tenant-isolation-max`, `vault-fernet-sessions`, `saas-multi-tenant`; JWT revoke, impersonation, INTERNAL_SERVICE_TOKEN checklist.
3. **`.cursor/skills/maxserver-postgresql/SKILL.md`** — Compose `postgres-patterns`, `database-migrations`, `backup-hybrid-storage`; migrations dir, `db_pg.py`, hybrid backup note.
4. **`.cursor/skills/maxserver-server-deploy/SKILL.md`** — Compose `deployment-patterns`, `docker-patterns`; `docker compose config`, `verify_deploy.sh`, Caddy, CI jobs from `.github/workflows/ci.yml`.
5. **`.cursor/skills/maxserver-campaign/SKILL.md`** — Compose `antiban-campaign-safety`, `celery-parity`; ADR 001–002 gates; never remove pacing without approval.
6. **`.cursor/skills/maxserver-testing/SKILL.md`** — Project commands: `MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/ -q`, e2e, compose-config; verifier evidence template.
7. **`.cursor/skills/maxserver-static-ui/SKILL.md`** — `static/index.html`, `auth.html`, `admin.html`; no build step; cookie auth / CSP notes from fix plans.

### P1 — Index and routing
8. **`.cursor/skills/README.md`** — Index: orchestration skills + maxserver-* + generic library + "do not load generics when facade exists".
9. **Update `ai-skills-system.mdc`** — Add rows for wired extra agents (secrets-credential, appsec-engineer, identity-access, campaign-antiban, backend-architect).
10. **Update `AGENTS.md` + `agents/README.md`** — Match expanded roster; fix skills/ library note.

### P2 — Optional / deferred
11. **`knowledge-catalog/sources.json`** — If external Agency/AAS/ECC repos are added later.
12. **Vendored `skills/` directory** — Only if user wants full upstream mirror; not required for operation.
13. **`docs/deps/`**, **`docs/lessons/`** — Phase 2/3 bootstrap optional.

---

## Generic skill → maxserver-* mapping

```
maxserver-fastapi-backend  ← fastapi-patterns + python-patterns
maxserver-postgresql       ← postgres-patterns + database-migrations + backup-hybrid-storage
maxserver-server-deploy    ← deployment-patterns + docker-patterns + redis-patterns (health)
maxserver-auth-security    ← security-review + tenant-isolation-max + vault-fernet-sessions + saas-multi-tenant
maxserver-campaign         ← antiban-campaign-safety + celery-parity
maxserver-testing          ← python-testing + mechanical-commands + CI refs
maxserver-static-ui        ← (new — no upstream generic; pointers to static/ + XSS/cookie notes)
```

---

## Validation checklist (post-proceed)

- [ ] All seven `maxserver-*` SKILL.md exist and are readable
- [ ] `context-loading` skill paths resolve
- [ ] Every specialist agent's "Read … SKILL.md" path exists
- [ ] `.cursor/skills/README.md` present
- [ ] `ai-skills-system.mdc` lists wired extra agents
- [ ] No doc claims vendored `skills/` unless directory exists
- [ ] HANDOFF.md updated with audit completion + next `/start-feature` suggestion

---

## Recommended first `/start-feature` after proceed

**"Harness repair: add maxserver-* facade skills + skills README + wire extra agents"** — Complexity LOW–MEDIUM, no product code changes, unblocks all future work.

---

## Related

- Codebase audit: `docs/CODEBASE-AUDIT.md`
- Harness audit: `docs/HARNESS-AUDIT.md`
