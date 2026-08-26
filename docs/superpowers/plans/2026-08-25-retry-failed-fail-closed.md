# Retry Failed Fail-Closed Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Stop the unsafe failed-message retry path from rewinding campaign progress or restarting a campaign.

**Architecture:** Keep the public route and authorization surface intact, but make the handler fail closed with HTTP 409. Do not add a partial retry implementation until campaign-scoped retry semantics are designed.

**Tech Stack:** FastAPI, Python 3.12, pytest, unittest.mock

**Approved design:** `docs/superpowers/specs/2026-08-25-production-remediation-wave1-design.md`

**Frozen scope:** Do not modify anti-ban code, role allocation, human timing, warmup/cooldown/local-day behavior, global settings, or worker-pool sizing.

---

### Task 1: Replace unsafe retry with a fail-closed contract

**Files:**
- Modify: `tests/test_campaign_auto_run.py:123`
- Modify: `app/routes_campaign.py:106-138`

**Step 1: Write the failing regression test**

Replace `test_retry_failed_sets_auto_run` with a test that seeds a failed send plus non-zero queue indices, calls `campaign_retry_failed`, and asserts:

- `HTTPException.status_code == 409`;
- `auto_run` remains `"0"`;
- all three queue indices remain unchanged;
- `_start_worker` is not awaited.

**Step 2: Run the test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests\test_campaign_auto_run.py::test_retry_failed_fails_closed_without_state_change -q`

Expected: FAIL because the current handler rewinds the queue and starts the worker.

**Step 3: Write the minimal implementation**

Replace the handler body with one `HTTPException(409, ...)`. Keep the route path unchanged. Remove all reads and mutations from this handler.

**Step 4: Run focused verification**

Run: `.venv\Scripts\python.exe -m pytest tests\test_campaign_auto_run.py tests\test_review_fix_authz.py -q`

Expected: PASS.

**Step 5: Controller review and commit**

Review `git diff -- app/routes_campaign.py tests/test_campaign_auto_run.py`, then commit only these two files.

