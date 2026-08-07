# Feature Lifecycle Workflow — MAX Sender

## Trigger

`/start-feature <business goal>`

## Phases

1. Context loading (`AGENTS.md` + PM state via `context-loading`)
2. Requirement analysis (≤2 clarifying questions)
3. Complexity classification (TRIVIAL | STANDARD | COMPLEX)
4. Feature Plan (short or full) via `project-orchestrator` mindset
5. User confirmation (`proceed`) — skip only for TRIVIAL
6. Architecture/ADR review if auth, vault, tenant, antiban, or deploy topology shifts
7. Scoped assignment (skills and/or domain agents)
8. Implementation with ownership / collision rules (`subagent-orchestrator`)
9. Mechanical checks (pytest / compose as relevant)
10. Security review if applicable (`security-review` skill / `appsec-engineer`)
11. Verification (`verifier` evidence)
12. Project-management update (parent: TASKS, HANDOFF, CURRENT_CONTEXT)

## Required Gate

Implementation cannot start until the user confirms the Feature Plan (non-TRIVIAL).

## Risks (Phase 1b)

STANDARD+ Feature Plans must include blast radius and mitigations (tenant leak, secret exposure, ban risk, data loss).

## Later phases (deferred)

- Dependency Graph (`docs/deps/`) — Phase 2
- Learning Layer (`docs/lessons/`) — Phase 3

See meta bootstrap `EVOLUTION-ROADMAP.md`.
