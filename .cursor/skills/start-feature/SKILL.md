---
name: start-feature
description: Start a new MAX Sender feature. Triggers orchestrator planning, Feature Plan output, and approval gate before implementation.
---

# Start Feature — MAX Sender

Use when the user says `/start-feature [description]` or asks to begin a new business feature.

## Trigger

```text
/start-feature [describe the business feature in plain language]
```

Examples:
```text
/start-feature валидировать серверный деплой Docker + Caddy + домен + PIN
/start-feature улучшить UI панели: loading states и адаптивная вёрстка
/start-feature реализовать server/app/hooks.py для production режима
```

## Process

### Step 1 — Load context

Read skill: `.cursor/skills/context-loading/SKILL.md`

### Step 2 — Invoke orchestrator mindset

Act as `@project-orchestrator` (readonly planning):
- Analyze requirement against product domain
- Classify complexity: LOW | MEDIUM | HIGH
- Decide ADR requirement
- Assign domain agents
- Define model strategy
- Identify risks

### Step 3 — Output Feature Plan

Use the exact format from `.cursor/agents/project-orchestrator.md`:

```
FEATURE PLAN
Feature: ...
Complexity: ...
ADR required: ...
Domains affected: ...
Agent Assignment: ...
Model Strategy: ...
Execution: ...
Risks: ...
Estimated effort: S | M | L
```

### Step 4 — STOP and wait

**Do not implement** until the user approves the Feature Plan.

Reply with:
> Feature Plan готов. Подтвердите план или укажите изменения перед реализацией.

### Step 5 — After approval

1. Load `.cursor/skills/subagent-orchestrator/SKILL.md`
2. Execute rounds per plan
3. Run `@verifier` before completion
4. Parent agent updates project-management files

## Complexity Shortcuts

| Signal | Typical routing |
|--------|-----------------|
| UI-only polish | frontend-engineer → verifier |
| Docker/domain | devops-engineer → qa-engineer → verifier |
| Campaign logic | campaign-specialist + backend-engineer → verifier |
| Auth/encryption | security-engineer review + backend-engineer → verifier |

## Anti-Patterns

- Skip Feature Plan for "quick fixes" that touch deploy or auth
- Start coding before approval
- Load all agents for every feature
