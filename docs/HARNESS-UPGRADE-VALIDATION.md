# Harness Upgrade Validation — MAX Sender

Adapted from `Global-AI-System/ai-agent-system-bootstrap/VALIDATION-CHECKLIST.md`  
Date: 2026-08-07  
Mode: `/audit-project` upgrade after proceed

## Bootstrap Analysis

- [x] Application logic read (audits + product docs)
- [x] Project type identified (multi-tenant FastAPI SaaS)
- [x] User roles identified (user, admin, service)
- [x] Core domains identified
- [x] Admin/backoffice identified
- [x] External integrations identified (MAX API, Telegram optional, Celery/Redis)
- [x] Security/privacy risks identified (payments N/A)
- [x] Technical stack documented
- [x] Domains mapped to agents vs skills vs rules

## Skills Inventory

- [x] Sources inspected via Gap Report / librarian
- [x] Only project-relevant skills selected (18)
- [x] Each skill has reason in Gap Report
- [x] Skills mapped to agents (intentional subsets in agent files)
- [x] No agent gets all skills
- [x] Procedural workflows are skills

## Static Context

- [x] `AGENTS.md` exists (~short map)
- [x] Thin rules under `.cursor/rules/` (7)
- [x] Always-on minimal (`mechanical-commands.mdc`)
- [x] Rules point to examples/skills
- [x] `docs/MASTER-AI-WORKFLOW.md` short map

## Agent Roster

- [x] `project-orchestrator.md` readonly Plan-tier Grok
- [x] `verifier.md` readonly Implement-tier Composer
- [x] Domain agents justified (8)
- [x] Allowed skills/rules/model/escalation/output per agent
- [x] MCP: GitHub required (`.cursor/mcp.json`); others opt-in
- [x] Not-created agents listed in `.cursor/agents/README.md`

## Start Feature Workflow

- [x] `start-feature/SKILL.md` exists
- [x] Complexity + proceed gate documented
- [x] Feature Plan formats + risks
- [x] `feature-lifecycle.md` exists

## Project Management State

- [x] `docs/PROJECT_PLAN.md` exists (KEEP)
- [x] `docs/adr/` exists with ADRs
- [x] CURRENT_CONTEXT, TASKS, DECISIONS, HANDOFF
- [x] DECISIONS indexes ADRs
- [x] Evolution Phase 2/3 deferred noted

## Mechanical / Hooks / MCP

- [x] Commands in AGENTS.md + always-on rule
- [x] Verifier requires evidence
- [x] MCP: GitHub required via `.cursor/mcp.json` + `GITHUB_PERSONAL_ACCESS_TOKEN`; others deferred opt-in
- [x] Hooks: 3 adapted (secrets read, prompt secrets, CI/test weaken warning)

## Model Routing

- [x] Plan = Grok orchestrator
- [x] Implement = Composer / verifier
- [x] Deep reserved (appsec default deep-capable; Feature Plan must justify)

## Acceptance (manual next step)

Ask:

```text
/start-feature Harden Celery vs in-process campaign start parity with tests
```

Expect Feature Plan + wait for proceed (not immediate coding).

## Validation status

**PASS** — harness upgrade complete for Gap Report ADD set.
