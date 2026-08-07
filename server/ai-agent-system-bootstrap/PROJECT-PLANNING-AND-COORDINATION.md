# Project Planning And Agent Coordination

## Purpose

This document ensures the generated AI development system can plan the whole project, maintain a shared todo list, prevent agents from overwriting each other, and preserve knowledge of what is done and what remains.

The bootstrap agent must create this coordination layer before real feature implementation begins.

## Required Planning Artifacts

Every generated project must have:

```text
PROJECT_ROADMAP.md or docs/PROJECT_PLAN.md
.cursor/project-management/TASKS.md
.cursor/project-management/CURRENT_CONTEXT.md
.cursor/project-management/PROJECT_STATUS.md
.cursor/project-management/DECISIONS.md
.cursor/project-management/HANDOFF.md
```

Use `PROJECT_ROADMAP.md` for strategic phases.
Use `.cursor/project-management/TASKS.md` for operational task tracking.

## Whole Project Plan

After reading the application logic, the bootstrap agent must create a project-level plan with:

- product vision;
- target users;
- user roles;
- core business domains;
- milestones;
- epics;
- features;
- technical foundations;
- integrations;
- testing strategy;
- release gates;
- known risks;
- out-of-scope items.

Recommended structure:

```md
# Project Plan

## Product Vision

## Users And Roles

## Core Domains

## Milestones

### Milestone 1 — Foundation

### Milestone 2 — Core Product

### Milestone 3 — Admin / Operations

### Milestone 4 — Integrations

### Milestone 5 — Production Readiness

## Release Gates

## Risks

## Out Of Scope
```

## Master Todo Registry

`.cursor/project-management/TASKS.md` must be the operational task registry.

Every task should have:

- stable title;
- status;
- owner or assigned agent;
- scope;
- dependencies;
- validation criteria;
- links to decisions or docs when relevant.

Allowed statuses:

```text
BACKLOG
PLANNED
IN_PROGRESS
REVIEW
COMPLETED
BLOCKED
```

Task template:

```md
### Feature: [Name]

Status: PLANNED
Owner: [parent agent or specialist]
Depends on: [task or none]
Scope:
- [files/domains]

Tasks:
- [ ] [task]

Validation:
- [ ] [test/check]

Notes:
- [context]
```

## Agent Work Ownership

Before assigning work, the orchestrator must define ownership.

Each subagent receives:

```text
Agent:
Task:
May read:
May edit:
Must not edit:
Depends on:
Expected output:
Validation:
```

Agents must not edit outside their assigned scope.

If an agent discovers it must touch a file outside scope, it must stop and report the required scope change to the parent/orchestrator.

## File Collision Prevention

The parent agent must prevent concurrent edits to the same file.

Rules:

- Do not assign the same file to multiple subagents in the same parallel round.
- If two agents need the same file, make one agent the owner and the other provide recommendations only.
- Shared files are edited in sequential rounds, not parallel rounds.
- The parent agent integrates changes after subagents finish.
- Subagents do not overwrite each other's work.

Collision matrix template:

```md
| File / Domain | Owner Agent | Readers | Edit Round | Notes |
|---------------|-------------|---------|------------|-------|
| [path] | [agent] | [agents] | Round 1 | [notes] |
```

## Context Handoff Rules

Each completed work session must update `HANDOFF.md` with:

- what was completed;
- files changed;
- decisions made;
- validation run;
- known issues;
- blocked work;
- next recommended action.

Subagents return handoff notes to the parent.
The parent writes the final shared `HANDOFF.md`.

## What Agents Must Read Before Work

Before starting any implementation, every parent agent must read:

```text
.cursor/project-management/CURRENT_CONTEXT.md
.cursor/project-management/PROJECT_STATUS.md
.cursor/project-management/TASKS.md
.cursor/project-management/DECISIONS.md
.cursor/project-management/HANDOFF.md
PROJECT_ROADMAP.md or docs/PROJECT_PLAN.md
```

Specialist subagents must receive a scoped context packet that includes:

- relevant task from `TASKS.md`;
- relevant decisions from `DECISIONS.md`;
- relevant handoff notes;
- allowed files;
- forbidden files;
- selected skills;
- selected rules;
- expected output.

## Feature Lifecycle Coordination

`/start-feature` must update planning state in this order:

1. Read current project state.
2. Check `TASKS.md` for existing related work.
3. Check `DECISIONS.md` for constraints.
4. Produce Feature Plan.
5. Wait for `proceed`.
6. Mark feature `IN_PROGRESS`.
7. Assign scoped work to agents.
8. Parent integrates results.
9. Run verifier.
10. Mark task `COMPLETED` only after verifier passes.
11. Add follow-up tasks for remaining work.
12. Update `HANDOFF.md`, `PROJECT_STATUS.md`, and `CURRENT_CONTEXT.md`.

## Done Criteria

A task can be marked `COMPLETED` only when:

- implementation matches the Feature Plan;
- assigned scope is complete;
- tests or validation checks are recorded;
- verifier reports `PASSED` or `PASSED WITH NOTES`;
- docs or API contracts are updated when relevant;
- project-management state is updated;
- no known blocker remains for that task.

## Blocked Work

If a task is blocked:

- mark it `BLOCKED` in `TASKS.md`;
- explain the blocker;
- record who or what can unblock it;
- add the next possible action;
- do not mark dependent tasks as ready.

## Anti-Patterns

Do not:

- let every agent edit shared files in parallel;
- let subagents independently change global PM-state;
- start a feature without checking existing tasks;
- create a roadmap but not connect it to `TASKS.md`;
- mark todo items complete without verifier evidence;
- lose unfinished work in chat history instead of `HANDOFF.md`;
- use vague scopes like "work on frontend";
- assign agents by technology only when the business domain needs ownership.

