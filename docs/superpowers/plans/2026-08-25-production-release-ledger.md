# Production Release Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace stale readiness claims with one current, evidence-linked GO/NO-GO ledger for the exact release branch.

**Architecture:** Add one dated human-readable ledger. It summarizes existing code/tests/workflows and distinguishes repository evidence from external gates; it introduces no runtime code or automation.

**Tech Stack:** Markdown, Git

**Spec:** `docs/superpowers/specs/2026-08-25-production-readiness-stages-1-3-design.md`

## Global Constraints

- Do not change anti-ban behavior, human behavior, roles, pacing, limits, local-day rules, global settings, or `worker_pool_size`.
- Do not treat local Windows passes as Linux, PostgreSQL, Docker, GitHub, VPS, or external-service evidence.
- Do not push or deploy.
- Human-facing prose needs evidence links, not source-grep tests.

---

### Task 1: Publish the current release ledger

**Files:**
- Create: `docs/PRODUCTION-READINESS-2026-08-25.md`
- Reference: `docs/FINAL-PRODUCTION-AUDIT-2026-08-21.md`
- Reference: `.github/workflows/ci.yml`
- Reference: `.github/workflows/deploy.yml`
- Reference: `docs/PRODUCTION-OPS.md`

**Interfaces:**
- Consumes: reviewed commits and verification output from the other stage 1–3 plans.
- Produces: the release decision used before push, staging, and production approval.

- [ ] **Step 1: Record exact identity and frozen scope**

Record branch, HEAD, merge base, remote URL, clean/dirty status, and the frozen
boundaries. Do not copy secrets or `.env` values.

- [ ] **Step 2: Reconcile the old P1 list**

Create a table for F-P1-01 through F-P1-08 with `CLOSED`, `OPEN`, or
`BLOCKED BY FROZEN SCOPE`, current file/test evidence, and the remaining gate.
Use current source and executed tests rather than the old audit verdict.

- [ ] **Step 3: Record stages 1–3 evidence**

Record exact commands and outcomes for focused tests, the full local suite,
`pip check`, JavaScript syntax, workflow/static checks, Bash syntax when
available, and `git diff --check`. List every skip and unavailable tool.

- [ ] **Step 4: Record external release gates**

Keep production NO-GO until all of these are evidenced for the exact SHA:

- full GitHub CI, including PostgreSQL, POSIX, dependency audit, and DR smoke;
- protected production environment and SSH host fingerprint;
- real VPS `.env`, DNS/TLS, resources, one app process, and all tenant pool
  values verified as 1 without changing them;
- production-like migration/restore rehearsal;
- isolated live MAX/proxy canary with separate authorization;
- explicit disposition of frozen role-percentage and UTC/local-day defects.

- [ ] **Step 5: Commit the ledger**

```powershell
git add docs/PRODUCTION-READINESS-2026-08-25.md
git commit -m "docs: add current production release ledger"
```
