# Production Runtime Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore a clean test baseline and add the two missing P1 regressions for cancelled sends and graceful shutdown.

**Architecture:** Keep production code untouched. Isolate mutable pytest module state, then exercise the existing send and shutdown contracts through their real state transitions with only external MAX calls and irreversible side effects replaced by narrow fakes.

**Tech Stack:** Python 3.12, pytest

**Spec:** `docs/superpowers/specs/2026-08-25-production-readiness-stages-1-3-design.md`

## Global Constraints

- Do not change anti-ban behavior, human behavior, role allocation, pacing, limits, local-day rules, global settings, or `worker_pool_size`.
- Do not modify production code for this test-isolation defect.
- Add no dependency or helper abstraction.
- No push, deployment, credentials, network, or external service access.

---

### Task 1: Isolate campaign-module fixture state

**Files:**
- Modify: `tests/test_campaign_modules.py:77-106`
- Verify: `tests/test_flood_wait.py:20-95`

**Interfaces:**
- Consumes: pytest's built-in `tmp_path` fixture and `pytest.MonkeyPatch.context()`.
- Produces: a `setup_local` fixture that yields the reloaded `main` module and restores `app.config` and `main` after all test-local patches are gone.

- [ ] **Step 1: Confirm the existing order-dependent failure**

Run:

```powershell
& 'C:\Users\Admin\Documents\Projects\server\.venv\Scripts\python.exe' -m pytest tests\test_campaign_modules.py tests\test_flood_wait.py::test_send_with_retry_sleeps_flood_wait -q --basetemp .pytest-tmp-red
```

Expected: `test_send_with_retry_sleeps_flood_wait` fails with `assert False is True`; the same flood-wait test passes when run alone. This RED has already been observed on commit `70caf57`.

- [ ] **Step 2: Replace the shared fixture monkeypatch with a local context**

Change `setup_local` so it no longer consumes the test's `monkeypatch` fixture:

```python
@pytest.fixture
def setup_local(tmp_path):
    import app.config as cfg
    import main as m

    with pytest.MonkeyPatch.context() as local_patch:
        local_patch.setenv("MAX_TEST", "1")
        local_patch.setenv("MAX_SERVER_MODE", "0")
        importlib.reload(cfg)
        importlib.reload(m)
        local_patch.setattr(m, "ROOT", tmp_path)
        m._refresh_data_paths()
        m.init_db()
        yield m

    importlib.reload(cfg)
    importlib.reload(m)
```

Remove the manual `prev_server` / `prev_test` save-and-restore block. Do not edit the two test bodies or production code.

- [ ] **Step 3: Verify GREEN in the failing order**

Run the Step 1 command again.

Expected: 5 passed.

- [ ] **Step 4: Verify both fixture consumers and the isolated flood-wait case**

Run:

```powershell
& 'C:\Users\Admin\Documents\Projects\server\.venv\Scripts\python.exe' -m pytest tests\test_campaign_modules.py tests\test_flood_wait.py -q --basetemp .pytest-tmp-green
```

Expected: 6 passed.

- [ ] **Step 5: Commit the test-only fix**

```powershell
git add tests/test_campaign_modules.py
git commit -m "test: isolate campaign module configuration"
```

### Task 2: Prove cancel-after-send does not requeue

**Files:**
- Create: `tests/test_campaign_send_cancel.py`
- Verify only: `app/campaign_send.py:230-306`
- Verify only: `app/campaign_worker.py:253-255`

**Interfaces:**
- Consumes: `SendTracker`, `send_with_retry`, and the existing SQLite send-log contract.
- Produces: a regression proving cancellation after MAX acknowledgement is persisted as sent and is never returned to the message bag.

- [ ] **Step 1: Add the behavior regression**

Build the smallest tenant SQLite fixture containing `profiles`, `groups`,
`queue_state`, `send_log`, and `settings`. Use a fake client whose
`send_message()` succeeds. Wrap the real `_persist_send_outcome` so its first
call raises `asyncio.CancelledError` and its interrupt-path call delegates to
the real function.

The test must assert all three observable outcomes:

```python
with pytest.raises(asyncio.CancelledError):
    asyncio.run(run_send())
assert tracker.may_requeue is False
assert sent_statuses == ["sent"]
assert returned_message_indexes == []
```

Patch only external MAX calls and logging. Exercise real `send_with_retry`,
real `SendTracker`, real interrupt persistence, and real SQLite writes.

- [ ] **Step 2: Run the new regression**

Run:

```powershell
& 'C:\Users\Admin\Documents\Projects\server\.venv\Scripts\python.exe' -m pytest tests\test_campaign_send_cancel.py -q --basetemp .pytest-tmp-cancel
```

Expected: PASS on the current implementation. This is evidence-only; if it
fails, stop and report the production defect instead of changing frozen logic.

- [ ] **Step 3: Mutation-check the regression**

Temporarily replace the test's expected tracker state with `True`, run the test
and confirm it fails, then revert that temporary test mutation. Do not mutate
production code.

- [ ] **Step 4: Commit the regression**

```powershell
git add tests/test_campaign_send_cancel.py
git commit -m "test: prove cancelled sends are not requeued"
```

### Task 3: Prove graceful shutdown order

**Files:**
- Modify: `tests/test_shutdown_handler.py`
- Verify only: `app/shutdown.py:32-110`

**Interfaces:**
- Consumes: `note_signal()`, `graceful_shutdown()`, and `reset_test()`.
- Produces: a behavioral regression for signal flagging, worker drain, and session encryption order.

- [ ] **Step 1: Add the async shutdown regression**

Patch `app.campaign_worker.stop_all_workers` and `main._encrypt_all_sessions`
with fakes that append to one `events` list. Inside a running loop, call
`note_signal(15)` and assert it returns `False`, then await
`graceful_shutdown(cancel_background=False)`.

Assert the externally important order exactly:

```python
assert events == ["stop-workers", "encrypt-sessions"]
```

Call `reset_test()` and reset the runtime before and after the scenario so the
test leaves no process-global shutdown state.

- [ ] **Step 2: Run and mutation-check the regression**

Run:

```powershell
& 'C:\Users\Admin\Documents\Projects\server\.venv\Scripts\python.exe' -m pytest tests\test_shutdown_handler.py -q --basetemp .pytest-tmp-shutdown
```

Expected: PASS. Temporarily reverse the expected event order, confirm failure,
then revert the test mutation.

- [ ] **Step 3: Commit the regression**

```powershell
git add tests/test_shutdown_handler.py
git commit -m "test: prove workers drain before encryption"
```
