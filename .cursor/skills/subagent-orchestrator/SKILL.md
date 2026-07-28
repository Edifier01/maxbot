---
name: subagent-orchestrator
description: Execute approved MAX Sender Feature Plans by delegating to domain agents in rounds. Parent agent owns integration and PM updates.
---

# Subagent Orchestrator — MAX Sender

Use **after Feature Plan approval** to coordinate implementation across specialist agents.

## Prerequisites

- [ ] Approved Feature Plan exists
- [ ] Context loaded via `context-loading` skill
- [ ] User explicitly approved implementation

## Parent Agent Responsibilities

The **parent agent** (main session) must:

1. Own integration across specialist outputs
2. Resolve conflicts between agents
3. Update project-management files at session end:
   - `CURRENT_CONTEXT.md` — if focus changed
   - `PROJECT_STATUS.md` — if milestones shifted
   - `TASKS.md` — check off completed items
   - `HANDOFF.md` — session summary
   - `DECISIONS.md` — if ADR approved

**Specialists do NOT edit project-management files.**

## Execution Model

### Round-based execution

Follow the Feature Plan's Execution rounds:

```
Round 1: [foundation — schema, hooks, infra]
Round 2: [core implementation]
Round 3: [polish, tests, docs]
```

### Delegation pattern

For each assigned agent:

1. State explicit scope boundary
2. List files they may touch
3. List files they must NOT touch
4. Define done criteria
5. Collect: files changed + verification performed

### Parallel vs sequential

| Parallel OK | Must be sequential |
|-------------|-------------------|
| UI mock + Docker config (no overlap) | DB schema → backend using new columns |
| Docs + test plan while coding | Security review before deploy merge |
| Independent file edits | Campaign logic after API contract set |

## Agent Invocation

Reference agent definitions in `.cursor/agents/`:

| Task type | Agent |
|-----------|-------|
| API, worker | backend-engineer |
| Campaign/antiban | campaign-specialist |
| UI | frontend-engineer |
| Schema | database-engineer |
| Docker/domain | devops-engineer |
| Tests | qa-engineer |
| Security audit | security-engineer |
| Final check | verifier |

## Model Selection Per Round

- **Composer 2.5:** implementation rounds (default)
- **GPT-5.5:** coordination, doc updates, test plan review
- **Opus:** only if Feature Plan specifies (ADR, security architecture)

## Verification Gate

Before marking feature complete:

1. Invoke `@verifier` with list of changes
2. Verdict must be PASS or PASS WITH NOTES (notes addressed)
3. Update TASKS.md via parent agent

## Session End Template (HANDOFF)

```markdown
## Last Session
**Date:** YYYY-MM-DD
**Feature:** [name]
**Agents used:** [list]

## What Was Done
- [bullet]

## Files Touched
- [paths]

## Verification
- [verifier verdict]

## Next Steps
- [recommended /start-feature]
```

## Anti-Patterns

- Let specialists expand scope without plan update
- Skip verifier on deploy/security changes
- Forget to update HANDOFF.md
- Break local exe while doing server work
