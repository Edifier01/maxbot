# Message Pool Serialization Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Prevent a global message-pool upload from racing with any tenant campaign start.

**Architecture:** Reuse the existing process-wide runtime as the single ownership point for one `asyncio.Lock`. Every `start_worker` and the upload handler take that same lock. Upload rejects with HTTP 409 when any registered tenant worker is active, before reading or writing the upload.

**Tech Stack:** asyncio, FastAPI, Python 3.12, pytest

**Approved design:** `docs/superpowers/specs/2026-08-25-production-remediation-wave1-design.md`

**Frozen scope:** Do not alter campaign pacing, anti-ban behavior, profile roles, human timing, global settings, or `worker_pool_size`.

---

### Task 1: Expose process-wide exclusion and active-worker state

**Files:**
- Modify: `app/campaign_runtime.py:58-130`
- Modify: `tests/test_audit_fixes.py:250-270`

**Step 1: Write failing runtime tests**

Add a test proving that `REGISTRY.any_worker_busy()` is false initially, true while any tenant runtime holds an unfinished task, and false after reset. Also assert reset replaces the process-wide message-pool lock with a fresh lock.

**Step 2: Run the focused test and confirm failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_audit_fixes.py -k "worker_busy or message_pool_lock" -q`

**Step 3: Implement the smallest shared interface**

Add `message_pool_lock` to `_AppRuntime`, recreate it in `reset_test`, and add `RuntimeRegistry.any_worker_busy()` using existing `worker_items()` and `CampaignRuntime.worker_busy()`.

Add a `ponytail:` comment documenting the single-process ceiling and the need for a distributed lock only if multi-process serving is introduced.

**Step 4: Verify the runtime tests**

Run the same focused command. Expected: PASS.

### Task 2: Serialize starts and uploads

**Files:**
- Modify: `app/campaign_worker.py:731-779`
- Modify: `app/routes_messages.py:1-40`
- Modify: `tests/test_routes_panel.py`

**Step 1: Write failing route/concurrency tests**

Add tests proving:

- upload returns 409 and does not call `save_messages_file` when any tenant worker is active;
- upload waits for `REGISTRY.app.message_pool_lock` before inspecting or reading the file;
- `start_worker` waits for that same lock before checking its tenant worker state.

Use an in-memory upload and fake unfinished task; do not start a real campaign.

**Step 2: Run tests to confirm the old code fails**

Run: `.venv\Scripts\python.exe -m pytest tests\test_routes_panel.py -k "message or upload or pool_lock" -q`

**Step 3: Implement serialization**

Wrap the existing `rt.worker_lock` start critical section with `REGISTRY.app.message_pool_lock`. In `upload_messages`, take the same lock, reject if `REGISTRY.any_worker_busy()`, then read, validate, save, and log while still holding it.

Keep the lock order global lock first, tenant lock second.

**Step 4: Verify the subsystem**

Run: `.venv\Scripts\python.exe -m pytest tests\test_routes_panel.py tests\test_campaign_auto_run.py tests\test_audit_fixes.py -q`

Expected: PASS.

**Step 5: Controller review and commit**

Review only the five owned files and commit them together after the implementation and spec reviews pass.

