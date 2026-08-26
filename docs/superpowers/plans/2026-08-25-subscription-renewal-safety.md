# Subscription Renewal Safety Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Let renewed tenants be stopped on a later expiry and serialize concurrent first-time subscription extensions.

**Architecture:** Prune renewed tenant IDs from the existing in-memory stopped set on every lifecycle tick. Lock the stable tenant row before reading subscription history so concurrent extension transactions for a tenant serialize even when no subscription row exists yet.

**Tech Stack:** PostgreSQL SQL, asyncio, Python 3.12, pytest

**Approved design:** `docs/superpowers/specs/2026-08-25-production-remediation-wave1-design.md`

**Frozen scope:** Do not change campaign rules, anti-ban, human behavior, global settings, or deployment configuration.

---

### Task 1: Clear renewed lifecycle markers

**Files:**
- Modify: `app/subscription_jobs.py:45-95`
- Create: `tests/test_subscription_jobs.py`

**Step 1: Write the failing lifecycle regression test**

Seed `_stopped_expired` with a tenant. On one tick make `subscription_active` return true and assert the marker is removed. On a later tick return that tenant from `tenants_recently_expired`, make `subscription_active` false, and assert `_stop_tenant_worker` is awaited and the marker is restored.

Stub warning queries, token cleanup, and Telegram scheduling; no PostgreSQL or network access.

**Step 2: Run and confirm failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_subscription_jobs.py -q`

**Step 3: Implement the lifecycle fix**

Before processing newly expired tenants, iterate over a tuple snapshot of `_stopped_expired` and discard IDs whose subscription is active.

**Step 4: Run focused verification**

Run the same command. Expected: PASS.

### Task 2: Serialize subscription extension transactions

**Files:**
- Modify: `app/db_pg.py:283-309`
- Modify: `tests/test_db_pg_helpers.py`

**Step 1: Write a failing SQL-order unit test**

Mock `_cursor(transaction=True)` and assert the first SQL statement in `extend_subscription` is `SELECT id FROM tenants WHERE id = %s FOR UPDATE`, followed by the existing subscription-history query.

**Step 2: Run and confirm failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_db_pg_helpers.py -k tenant_row -q`

**Step 3: Add the tenant-row lock**

Execute the tenant-row `SELECT ... FOR UPDATE` immediately after entering the transaction. Keep the expiry calculation and INSERT unchanged.

**Step 4: Verify the subsystem**

Run: `.venv\Scripts\python.exe -m pytest tests\test_subscription_jobs.py tests\test_db_pg_helpers.py -q`

Expected: unit tests PASS. PostgreSQL integration remains a separate release gate.

**Step 5: Controller review and commit**

Review and commit only the four owned files after implementation and spec review.

