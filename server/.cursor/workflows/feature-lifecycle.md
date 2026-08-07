# Feature Lifecycle — MAX Sender Server

## Trigger

```text
/start-feature <business goal>
```

## Phases

| # | Phase | Owner | Gate |
|---|-------|-------|------|
| 1 | Context loading | parent agent | read PM + PROJECT_PLAN |
| 2 | Requirement analysis | project-orchestrator | — |
| 3 | Complexity classification | project-orchestrator | TRIVIAL / STANDARD / COMPLEX |
| 4 | Feature Plan | project-orchestrator | includes Model Strategy |
| 5 | User confirmation | user | **`proceed` required** |
| 6 | Architecture/ADR | orchestrator + security if needed | if HIGH + security |
| 7 | Mission Brief + assignment | parent agent | file ownership defined |
| 8 | Implementation | specialists | scoped rounds |
| 9 | Testing | qa-engineer or builder | evidence recorded |
| 10 | Security review | security-engineer | if auth/vault/tenant/deploy |
| 11 | Verification | verifier | PASSED / FAILED |
| 12 | PM update | parent agent | HANDOFF, STATUS, TASKS |

## Required Gate

Implementation **cannot start** until user confirms Feature Plan (`proceed`, `ok`, `yes`, `да`).

TRIVIAL changes (1 file, <10 lines, no security impact) may bypass orchestrator.

## Done Criteria

Task → COMPLETED only when:

- Implementation matches Feature Plan
- Validation evidence recorded
- Verifier reports PASSED or PASSED WITH NOTES
- PM state updated

## Blocked Work

Mark BLOCKED in `TASKS.md` with unblock criteria. Do not mark dependents as ready.

## Domain Gates

| Domain | Gate |
|--------|------|
| Deploy | `maxserver-server-deploy` checklist + `docker compose config` |
| Auth/secrets | `maxserver-auth-security` + security-engineer if HIGH |
| PG DDL | backup note + `maxserver-postgresql` |
| Campaign | `maxserver-campaign` — no pacing removal without approval |
| UI | `maxserver-static-ui` + smoke if risk warrants |

## Model Routing (summary)

- **GPT-5.5** — planning, orchestration, docs
- **Composer 2.5** — implementation, tests, routine verification
- **Opus** — security architecture (security-engineer default)

See `docs/MASTER-AI-WORKFLOW.md`.
