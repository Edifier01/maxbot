---
name: start-feature
description: Starts controlled feature work via /start-feature — load context, classify complexity, Feature Plan, wait for proceed, then implement and verify. Use for non-trivial product changes.
---

# Start Feature

## Purpose

Turn a business goal into a gated implementation sequence for MAX Sender.

## When To Use

- User runs `/start-feature <business goal>`
- Non-trivial feature, refactor, security, or ops change

## When Not To Use

- Pure questions / read-only exploration
- TRIVIAL edits may bypass orchestrator (see classification)

## Required Inputs

- Business goal string
- Loaded context (use `context-loading`)

## Workflow

1. Load context (`context-loading`).
2. Ask at most two clarifying questions if goal is unclear.
3. Classify: **TRIVIAL** | **STANDARD** | **COMPLEX** (see below).
4. **TRIVIAL:** edit directly; quick checks; update HANDOFF if needed.
5. **STANDARD/COMPLEX:** invoke `project-orchestrator` mindset; produce Feature Plan (short or full).
6. **Wait for explicit `proceed` / `ok` / `yes` / `да` / `go ahead` / `начинай`.**
7. Execute via parent and/or `subagent-orchestrator` Mission Briefs.
8. Mechanical checks (`AGENTS.md` commands).
9. Run `verifier` with evidence.
10. Update `TASKS.md`, `HANDOFF.md`, `CURRENT_CONTEXT.md` (parent owns PM).

### Complexity

| Class | Criteria | Action |
|-------|----------|--------|
| TRIVIAL | ~1 file, ~≤10 lines, no logic/security/data impact | Bypass orchestrator |
| STANDARD | 1–3 files, 1–2 domains, no architecture change | Short Feature Plan → proceed → implement → verify |
| COMPLEX | ≥4 files, ≥3 domains, architecture, auth/vault/tenant/antiban/deploy secrets | Full plan + ownership matrix + risks (+ ADR if needed) |

### Feature Plan must include

- Scope, agents (smallest set), models/tiers, skills, risks, validation/mechanical checks
- COMPLEX: execution rounds + May read / May edit / Must not edit collision matrix

## Validation Checklist

- [ ] Did not code before `proceed` (non-TRIVIAL)
- [ ] Verifier evidence recorded
- [ ] PM updated

## Related Agents

- `project-orchestrator`, `verifier`, domain agents as planned

## Related Rules

- `mechanical-commands.mdc`
