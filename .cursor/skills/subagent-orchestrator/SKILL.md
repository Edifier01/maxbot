---
name: subagent-orchestrator
description: Executes approved Feature Plans by decomposing Mission Briefs, running independent agents in parallel, and enforcing edit scopes. Use after proceed when specialists are assigned.
---

# Subagent Orchestrator

## Purpose

Execute an approved Feature Plan with scoped specialists. This is a **skill**, not a second orchestrator agent.

## When To Use

- After user `proceed` on STANDARD/COMPLEX plans that assign specialists
- Parallel independent workstreams with clear file ownership

## When Not To Use

- TRIVIAL work
- Single-agent / parent-only implementation
- Procedural checklists better done as skills alone

## Required Inputs

- Approved Feature Plan
- Agent roster subset
- Collision matrix

## Workflow

1. Split plan into Mission Briefs (one per specialist or sequential wave).
2. Each brief MUST include: Goal, May read, May edit, Must not edit, Skills, Rules, Depends on, Expected output, Validation.
3. Run independent briefs in parallel; dependent briefs sequentially.
4. Reject any specialist expanding scope (drive-by refactors).
5. Parent merges results; resolve conflicts by ownership matrix.
6. Parent runs mechanical checks; invoke `verifier`.
7. Parent updates PM state; specialists only return handoff notes.

## Validation Checklist

- [ ] No two agents editing the same files in parallel
- [ ] Shared files sequential or single owner
- [ ] Verifier ran before COMPLETED

## Related Agents

- All domain agents; `verifier`; parent integrates

## Related Rules

- Domain glob rules as assigned in briefs
