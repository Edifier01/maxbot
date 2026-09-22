# MAXBOT Complete Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the production-readiness candidate into the current `main` line, reconcile documentation/configuration with the enforced runtime policy, and leave a verified local release candidate without falsely claiming production or live-MAX acceptance.

**Architecture:** Apply the existing candidate commits in chronological order onto a fresh branch based on current `main`, resolving only integration conflicts. The candidate already contains the daily-plan storage fix, UI-safe-error behavior, browser contracts, and evidence updates; remaining work is to reconcile stale operational documentation and configuration examples to the current fixed policies. External MAX, VPS, Docker-image metadata, GitHub push, and production verification remain explicit gates and are recorded as blocked/not run when unavailable.

**Tech Stack:** Python 3.12, pytest, SQLite/PostgreSQL adapters, vanilla HTML/CSS/JavaScript, Playwright, Docker Compose, Git.

**Spec:** `docs/audit/2026-09-20-maxbot-master-v3-independent-audit.md`, `docs/superpowers/plans/2026-09-20-maxbot-safe-remediation-addendum.md`, and the current repository README/ADR policy.

## Global Constraints

- Preserve fail-closed boundaries for real MAX actions; tests use fake or mocked providers only.
- Keep `maxapi-python` pinned to `2.4.1`.
- Keep one campaign owner/worker, fixed UTC+3 accounting, fixed one-third role distribution, and no artificial presence.
- Do not expose or persist secrets; do not create `.env` or run live MAX actions.
- Bind new evidence to the final candidate SHA and label unavailable external gates `BLOCKED` or `NOT RUN`.
- Do not rewrite history or force-push.

## Review Focus

- Global message-library reads must use global storage while daily plans remain tenant-local; the claim path must return a real slot rather than a waiting decision.
- Structured safe errors must render without leaking raw provider or exception details.
- Fixed safety policies must agree across runtime code, UI, ADRs, runbooks, `.env.example`, and compose defaults.
- Browser evidence must distinguish local/hosted CI checks from unrun 200% zoom, full contrast, offline, and production checks.
- Audit records must identify the final SHA and must not convert local or historical evidence into production proof.

---

### Task 1: Establish isolated baseline and reproduce the daily-plan defect

**Files:**
- Read: `app/campaign_worker.py`, `main.py`, `tests/test_daily_plan_integration_v2.py`
- Create: `.superpowers/sdd/2026-09-22-maxbot-complete-remediation/progress.md`

**Interfaces:**
- Consumes: current `main` at `a7b62704c1e6ceed5d01d1105649a480903806cb`.
- Produces: a recorded RED result for `test_daily_slot_identity_is_carried_into_operation_and_send_log` and a clean isolated branch.

- [x] **Step 1: Record the plan ledger and baseline SHA.**

- [x] **Step 2: Run the focused daily-plan test on the unmodified baseline.**

  Run:

  ```bash
  env MAX_TEST=1 MAX_SERVER_MODE=1 JWT_SECRET=local-test-secret \
    /home/edifier/projects/maxbot/.venv/bin/python -m pytest -q \
    tests/test_daily_plan_integration_v2.py::test_daily_slot_identity_is_carried_into_operation_and_send_log
  ```

  Expected: FAIL with `WaitDecision(reason='waiting_pool_or_no_queued_slot')` before the candidate storage fix.

### Task 2: Integrate the candidate code, tests, and evidence commits

**Files:**
- Modify: `app/campaign_worker.py`, `main.py`, `static/index.html`, `static/js/index.js`, `static/js/admin.js`
- Modify: `tests/test_daily_plan_integration_v2.py`, `tests/test_error_taxonomy_v2.py`, `tests/test_ui_assets_contract.py`, `tests/test_ui_review_contract.py`, `tests/browser/*.js`
- Modify: `docs/audit/*.md`, `docs/superpowers/plans/2026-09-21-maxbot-browser-ci.md`

**Interfaces:**
- Consumes: candidate commits `e4837a1` through `a684cf4` in chronological order.
- Produces: candidate code on the new branch with the daily-plan, safe-message, accessibility, and browser-contract changes.

- [x] **Step 1: Cherry-pick the 14 candidate commits in chronological order.**

  Use `git cherry-pick e4837a1 134ee4b eced4a6 1d50bec 24ecde6 36d27c3 1b97984 3c40b65 2b28832 c5f5298 fcd0757 90e7323 24b75c3 a684cf4` and resolve only conflicts caused by the three newer `main` commits.

- [x] **Step 2: Run the daily-plan regression test and the related campaign/ledger tests.**

  Expected: the previously failing slot identity test passes, and no related test fails.

- [x] **Step 3: Review the resulting diff for secrets, generated artifacts, unrelated rewrites, and candidate-SHA references.**

### Task 3: Reconcile runtime-policy documentation and configuration examples

**Files:**
- Modify: `docs/HOW-IT-WORKS.md`
- Modify: `docs/adr/002-campaign-scale-pacing.md`, `docs/adr/005-admin-tenant-worker-pool.md`
- Modify: `.env.example`, `docker-compose.yml`
- Modify: `docs/PROJECT_PLAN.md`, `docs/PRODUCTION-OPS.md`, `docs/audit/final-review.md`, `docs/audit/release-gate.md`, `docs/audit/ui-review.md`, `docs/audit/verification.md`

**Interfaces:**
- Consumes: enforced runtime policies in `app/routes_admin.py`, `app/campaign_worker.py`, `app/pacing_policy.py`, and UI policy tests.
- Produces: documentation that describes one worker, UTC+3, fixed role thirds, no artificial presence, and honest local/external gate status.

- [x] **Step 1: Replace obsolete artificial-presence/auto-join/parallel-worker descriptions with the current fail-closed campaign flow.**

- [x] **Step 2: Change configuration examples and ADR statements to the enforced values (`WORKER_POOL_SIZE=1`, UTC+3, fixed role distribution, no presence controls).**

- [x] **Step 3: Update the release/audit handoff to the runtime/test candidate SHA and preserve `BLOCKED`/`NOT RUN` labels for production, normative, CVE, secret-history, and real-MAX gates.**

### Task 4: Run local verification and browser/static checks

**Files:**
- Read: `README.md`, `.github/workflows/ci.yml`, `package.json`
- Modify: none unless a verification-discovered defect has a focused regression test.

**Interfaces:**
- Consumes: integrated branch from Tasks 1–3.
- Produces: fresh exit-code evidence for focused tests, full test collection/suite, syntax/static checks, and available browser/compose checks.

- [x] **Step 1: Run the focused safety, campaign, recovery, UI, and browser-contract tests.**
- [x] **Step 2: Run the complete `tests/` suite with a bounded timeout and record the environment-only hang separately.**
- [x] **Step 3: Run Python/JS/shell/JSON checks, `git diff --check`, and `docker compose config -q`.**
- [x] **Step 4: Use the pinned Playwright package against a bounded local server; the browser gate is `BLOCKED` by the Chromium sandbox and Docker/production gates remain separately unrun.**
- [x] **Step 5: Bind current evidence to the runtime/test SHA and perform the final diff/status review.**

### Task 5: Commit the verified local candidate and prepare integration

**Files:**
- Modify: Git history only.

**Interfaces:**
- Consumes: green or explicitly classified verification from Task 4.
- Produces: a local commit-ready branch suitable for a non-force local merge into `main`; no deployment claim.

- [ ] **Step 1: Commit documentation reconciliation and verification evidence only after fresh verification.**
- [ ] **Step 2: Verify the branch status, ancestry, exact SHA, and absence of secrets/generated artifacts.**
- [ ] **Step 3: Merge locally into `main` only if the merged result remains verified; do not push or deploy from a failed result.**

---

## Self-review

- Task 1 produces the RED evidence required before accepting the existing production fix.
- Task 2 consumes the existing candidate commits and produces the code/tests needed by Task 3.
- Task 3 touches only policy documentation/configuration and does not alter runtime behavior.
- Task 4 verifies the merged result, with environment limitations recorded instead of hidden.
- Task 5 is intentionally gated by Task 4 and does not authorize external deployment or live MAX actions.
