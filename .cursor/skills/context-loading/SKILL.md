---
name: context-loading
description: Loads MAX Sender project state (AGENTS.md and PM files) before non-trivial planning or implementation. Use at session start and before /start-feature.
---

# Context Loading

## Purpose

Ensure agents know current context, tasks, decisions, and handoff notes with Minimum Viable Context.

## When To Use

- Before `/start-feature` or any STANDARD/COMPLEX work
- When resuming after a gap in conversation

## When Not To Use

- Pure TRIVIAL one-line edits with clear local context
- Do not dump entire PM folder into every subagent — prefer scoped packets

## Required Inputs

- Workspace root = MAX Sender server project

## Workflow

1. Read `AGENTS.md` (commands + guardrails).
2. Read `.cursor/project-management/CURRENT_CONTEXT.md` and `HANDOFF.md`.
3. Skim `TASKS.md` for in-flight/blocked items related to the goal.
4. Check `DECISIONS.md` / relevant ADRs if architecture or prior decisions touch the goal.
5. Open only the product docs needed (`HOW-IT-WORKS`, `PRODUCTION-OPS`, specific ADR).
6. Summarize in ≤10 bullets for the parent; pass specialists a scoped packet.

## Validation Checklist

- [ ] Commands/guardrails known
- [ ] No conflicting in-flight task ignored
- [ ] Relevant ADRs noted

## Related Agents

- `project-orchestrator`, parent agent

## Related Rules

- `mechanical-commands.mdc`
