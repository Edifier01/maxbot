# Generated Artifact Cleanup Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Remove tracked audit/test artifacts and stop them from re-entering source control.

**Architecture:** Delete only the three approved generated directory families and ignore those exact families in Git and Docker contexts. Do not touch repository history or any rule/configuration file outside the two ignore files.

**Tech Stack:** Git, PowerShell, ignore patterns

**Approved design:** `docs/superpowers/specs/2026-08-25-production-remediation-wave1-design.md`

**Frozen scope:** Do not restore, edit, or delete rule files, AGENTS files, anti-ban logic, human-behavior logic, or global settings.

---

### Task 1: Delete only approved generated trees

**Files:**
- Delete: `.audit-full-20260822/`
- Delete: `.audit-webhook/`
- Delete: `.pytest-tmp/`
- Modify: `.gitignore`
- Modify: `.dockerignore`

**Step 1: Capture the failing repository check**

Run: `git ls-files -- .audit-full-20260822 .audit-webhook .pytest-tmp`

Expected before cleanup: tracked generated files are listed.

**Step 2: Validate deletion targets**

Resolve each absolute path and verify it is a child of `C:\Users\Admin\Documents\Projects\server`. Do not use globs for deletion.

**Step 3: Apply the minimal cleanup**

Delete exactly the three resolved directories. Add `.audit-*` and `.pytest-tmp` to both ignore files.

**Step 4: Verify cleanup**

Run:

- `git ls-files -- .audit-full-20260822 .audit-webhook .pytest-tmp`
- `git check-ignore .audit-example .pytest-tmp/example`
- `git diff --check`

Expected: the first command is empty; the second identifies both ignore rules; diff check passes.

**Step 5: Controller review and commit**

Verify `git status --short` shows deletions only below the three approved trees plus the two ignore files, then commit that exact scope.
