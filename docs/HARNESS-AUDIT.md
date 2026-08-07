# Harness Audit — MAX Sender Server

**Mode:** `/audit-project` phase 2  
**Target:** `C:\Users\Maga\Documents\Projects\server`  
**Generated:** 2026-08-07  
**Baseline:** `Global-AI-System/ai-agent-system-bootstrap/AGENT-SYSTEM-SPEC.md`  

---

## 1. Inventory vs bootstrap mandatory core

| Artifact | Bootstrap expectation | Present? | Notes |
|----------|----------------------|----------|-------|
| `AGENTS.md` | Mandatory | **No** | Missing project agent map / commands |
| `.cursor/agents/project-orchestrator.md` | Mandatory (readonly, Grok plan-tier) | **No** | |
| `.cursor/agents/verifier.md` | Mandatory (readonly, skeptical) | **No** | |
| `.cursor/agents/README.md` | Expected | **No** | |
| Domain / work-type agents | Optional, quality-driven | **No** | Needed for auth/vault/tenant/campaign/ops |
| `.cursor/skills/context-loading/` | Mandatory | **No** | |
| `.cursor/skills/start-feature/` | Mandatory | **No** | |
| `.cursor/skills/subagent-orchestrator/` | Mandatory | **No** | |
| Domain skills | Optional / REQUIRED from Gap | **No** | |
| `.cursor/rules/*.mdc` | Thin always/glob rules | **No** | |
| `.cursor/hooks.json` | Optional | **No** | ECC patterns may ADD |
| MCP project config | Optional | **No** | |
| `.cursor/project-management/CURRENT_CONTEXT.md` | Mandatory | **No** | |
| `.cursor/project-management/TASKS.md` | Mandatory | **No** | |
| `.cursor/project-management/DECISIONS.md` | Mandatory | **No** | ADRs exist under `docs/adr/` but no DECISIONS index |
| `.cursor/project-management/HANDOFF.md` | Mandatory | **No** | |
| `.cursor/workflows/feature-lifecycle.md` | Mandatory | **No** | |
| `docs/PROJECT_PLAN.md` | Mandatory | **Yes** | Product plan present |
| `docs/MASTER-AI-WORKFLOW.md` | Mandatory | **No** | |
| `docs/adr/` | Phase 1 Architecture Memory | **Yes** | 001–003 present |
| `docs/deps/`, `docs/lessons/` | Phase 2/3 optional | **No** | Defer until needed |

**Other AI config searched:** no `CLAUDE.md`, `.cursorrules`, `mcp.json`, `.mcp.json`, or `.cursor/` tree.

---

## 2. Quality issues / absences

1. **Total harness absence** — agents cannot load PM state, proceed gates, or Feature Plans; every session starts cold from README/docs.
2. **No proceed gate / Feature Plan workflow** — high-risk domains (tenant, vault, campaign) lack orchestrated review before edits.
3. **No verifier** — CI exists, but no skeptical agent requiring evidence against Feature Plan.
4. **No mechanical-command map for agents** — pytest/compose commands live in README/CI only.
5. **ADRs without DECISIONS.md index** — architecture memory partially present; bootstrap expects PM `DECISIONS.md` linking ADRs.
6. **No glob rules** for Python/FastAPI/tenant-path/vault conventions — agents may violate isolation patterns.
7. **No hooks** for stop/grind or secret-scan patterns (ECC may recommend selective hooks).
8. **Product docs are strong** — do **not** replace HOW-IT-WORKS / PRODUCTION-OPS; harness should **point to** them.

---

## 3. Keep / seed material (product docs → harness pointers)

These are **not** Cursor harness files but should be **KEEP** and linked from AGENTS.md / PM after upgrade:

- `README.md`
- `docs/HOW-IT-WORKS.md`
- `docs/PRODUCTION-OPS.md`
- `docs/PROJECT_PLAN.md`
- `docs/adr/001-tenant-worker-isolation.md`
- `docs/adr/002-campaign-scale-pacing.md`
- `docs/adr/003-worker-module-extraction-deferred.md`
- `.github/workflows/ci.yml` / `deploy.yml` (mechanical gates)
- `tests/` suite (verifier evidence source)

---

## 4. Harness audit verdict

**Bootstrap mandatory core: 0% installed.**  
Product documentation and ADRs are a solid foundation for linking, but the Cursor AI system (agents, skills, rules, PM, workflows) must be generated wholesale after Gap Report `proceed`. Prefer **skills** for procedural deploy/test/context flows; prefer **domain agents** for high-risk isolation (security, tenant, campaign/anti-ban, devops).

---

## Related

- Codebase audit: `docs/CODEBASE-AUDIT.md`
- Gap Report: `C:\Users\Maga\Documents\Projects\Global-AI-System\knowledge-catalog\reports\max-sender-gap.md`
