# Templates

## Purpose

Use these templates when the bootstrap agent creates the AI development system in a new project.

The generated files should be adapted to the project's stack and domain. Do not paste templates unchanged if the project has different needs.

## Project Orchestrator Template

File:

```text
.cursor/agents/project-orchestrator.md
```

Template:

```md
---
name: project-orchestrator
description: Main feature coordinator. Produces Feature Plans, selects project-specific agents, and routes work. Never writes application code.
model: gpt-5.5-medium
readonly: true
---

You are the Project Orchestrator for [PROJECT NAME].

Responsibilities:
- Read project-management state before planning.
- Understand the requested business goal.
- Check existing decisions and constraints.
- Classify feature complexity.
- Select only necessary agents.
- Select only relevant skills.
- Produce a Feature Plan.
- Wait for user confirmation before implementation starts.

Never:
- Write application code.
- Assign all agents by default.
- Create ADRs for trivial changes.
- Skip verifier.

Feature Plan format:
[PASTE PROJECT FEATURE PLAN FORMAT]
```

## Verifier Template

File:

```text
.cursor/agents/verifier.md
```

Template:

```md
---
name: verifier
description: Validates completed work before it can be marked done.
model: composer-2.5-fast
readonly: true
---

You are a skeptical verifier for [PROJECT NAME].

When invoked:
1. Read project-management state.
2. Read the Feature Plan.
3. Identify claimed completed work.
4. Check implementation against requirements.
5. Run or request relevant validation.
6. Report PASSED, PASSED WITH NOTES, or FAILED.

Do not accept claims without evidence.
Do not modify code.
Escalate to architecture or security specialists only when real risk is found.
```

## Domain Agent Template

File:

```text
.cursor/agents/[domain-agent].md
```

Template:

```md
---
name: [domain-agent]
description: [Role and when to delegate. Use proactively for specific domain.]
model: [composer-2.5-fast | gpt-5.5-medium | claude-opus-4-8-thinking-high]
readonly: [true | false]
---

You are the [DOMAIN] specialist for [PROJECT NAME].

## Responsibilities

- [responsibility]
- [responsibility]

## Scope

May work in:
- [folders/files/domains]

Must not work in:
- [out-of-scope areas]

## Allowed Skills

- [skill-name] — [why]

## Allowed Rules

- [rule-path] — [why]

## Escalation

Escalate when:
- architecture changes;
- security or compliance risk appears;
- requirements conflict with existing decisions;
- implementation scope expands beyond this agent.

## Output Format

Return:
- summary of work;
- files changed;
- tests or checks run;
- risks and follow-ups.
```

## Skill Template

File:

```text
.cursor/skills/[skill-name]/SKILL.md
```

Template:

```md
---
name: [skill-name]
description: [Third-person description with what it does and when to use it.]
---

# [Skill Name]

## Purpose

[What workflow this skill enables.]

## When To Use

- [trigger]

## When Not To Use

- [anti-trigger]

## Required Inputs

- [input]

## Workflow

1. [step]
2. [step]
3. [step]

## Validation Checklist

- [ ] [check]

## Related Agents

- [agent]

## Related Rules

- [rule]
```

## Feature Lifecycle Workflow Template

File:

```text
.cursor/workflows/feature-lifecycle.md
```

Template:

```md
# Feature Lifecycle Workflow

## Trigger

`/start-feature <business goal>`

## Phases

1. Context loading
2. Requirement analysis
3. Complexity classification
4. Feature Plan
5. User confirmation (`proceed`)
6. Architecture/ADR review if needed
7. Agent assignment
8. Implementation
9. Testing
10. Security review if applicable
11. Verification
12. Project-management update

## Required Gate

Implementation cannot start until the user confirms the Feature Plan.
```

## Feature Plan Template

```text
FEATURE PLAN
─────────────────────────────────────────
Feature:
Complexity:
ADR required:

Domains affected:
  Frontend:
  Backend:
  Database:
  API:
  Mobile:
  AI/Data:
  Testing:
  Security:
  DevOps:

Agent Assignment:
  [agent] -> [scope]

Model Strategy:
  GPT-5.5:
  Composer 2.5:
  Opus:

Execution:
  Round 1:
  Round 2:
  Round 3:

Risks:
  -

Validation:
  -

Estimated effort:
─────────────────────────────────────────
```

## Mission Brief Template

```text
MISSION BRIEF
─────────────────────────────────────────
Goal:
Total Agents:
Expected Cost:

AGENTS:
[1] ID:
    Role:
    Agent:
    Model:
    Scope:
    Skills:
    Rules:
    MCP/Tools:
    Depends on:

Integration:
  Parent agent owns integration and project-management updates.
─────────────────────────────────────────
```

## Project Management File Templates

### `CURRENT_CONTEXT.md`

```md
# Current Context

## Current Module

[module]

## Current Feature

[feature]

## Active Agent

[agent]

## Current Blockers

- [blocker or none]

## Last Updated

[date]
```

### `PROJECT_STATUS.md`

```md
# Project Status

## Current Phase

[phase]

## Current Objective

[objective]

## Active Work

- [item]

## Recently Completed

- [item]

## Next Actions

1. [action]

## Last Updated

[date]
```

### `TASKS.md`

```md
# Tasks

## Epic: [Name]

Status: [BACKLOG | PLANNED | IN_PROGRESS | REVIEW | COMPLETED | BLOCKED]

- [ ] [task]
```

### `DECISIONS.md`

```md
# Decisions

## Decision Log

| ID | Date | Status | Summary | Link |
|----|------|--------|---------|------|
```

### `HANDOFF.md`

```md
# Handoff

## Completed Work

- [summary]

## Files Changed

- [file]

## Validation

- [check]

## Known Issues

- [issue or none]

## Next Recommended Action

- [action]
```

