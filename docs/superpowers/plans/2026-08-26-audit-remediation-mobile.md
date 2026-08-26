# MAX Sender Audit Remediation and Mobile UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the confirmed production blockers, fix UTC+3 accounting, keep fixed-third roles, and make the existing UI usable on mobile.

**Architecture:** Keep the current FastAPI, per-tenant SQLite, pymax, and vanilla UI architecture. Fix shared boundaries in place: a restorable single-worker queue claim, an outer vault cleanup invariant, centralized live-mutation/proxy validation, and CSS/renderer changes with no new dependency.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite, asyncio, pytest, vanilla JavaScript, HTML/CSS.

**Spec:** `docs/superpowers/specs/2026-08-26-audit-remediation-mobile-design.md`

## Global Constraints

- Operational local time is fixed at UTC+3; stored database timestamps remain UTC.
- Rotation roles remain fixed thirds.
- Effective `worker_pool_size` is always `1`.
- Unknown MAX send outcomes are never automatically retried.
- Add no dependency or new queue subsystem.
- Do not push, deploy, send a live MAX message, or run a live proxy mutation.
- Every production behavior starts with a focused failing test.

---

### Task 1: Fixed policies and clean test bootstrap

**Files:**
- Modify: `main.py`
- Modify: `app/routes_models.py`
- Modify: `app/routes_admin.py`
- Modify: `app/routes_settings.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_admin_tenant_settings.py`
- Modify: `tests/test_global_pacing_settings.py`
- Modify: `tests/test_saas_ux_static.py`

**Interfaces:**
- Produces: `LOCAL_TIMEZONE = timezone(timedelta(hours=3))`; `_pool_size() -> int` always returns `1`.
- Produces: settings responses expose fixed values but no mutable timezone, role-share, or pool controls.

- [x] **Step 1: Write failing policy tests**

```python
def test_pool_size_is_fixed_to_one(m):
    m.set_setting("worker_pool_size", "32")
    assert m._pool_size() == 1

def test_local_now_is_always_utc_plus_three(m):
    m.set_setting("timezone_offset_hours", "-8")
    assert m._local_now().utcoffset().total_seconds() == 3 * 3600
```

Update static tests to require the removal of `workerPool`, `tzOffset`,
`roleActivePct`, `roleQuietPct`, and `btnRetryFailed` controls.

- [x] **Step 2: Run tests and verify RED**

Run:
`python -m pytest tests/test_admin_tenant_settings.py tests/test_global_pacing_settings.py tests/test_saas_ux_static.py -q --basetemp=.pytest-tmp/task1-red`

Expected: FAIL because pool/timezone remain configurable and controls exist.

- [x] **Step 3: Implement fixed policies**

Use one UTC+3 timezone constant, return `1` from `_pool_size`, restrict the
admin settings model to `Literal[1]`, and drop mutable timezone/role-share/pool
keys from settings updates. Seed an idempotent test database in the test
bootstrap instead of relying on ignored user `data/`.

- [x] **Step 4: Verify GREEN**

Run the same focused tests; expected PASS.

- [x] **Step 5: Commit**

```text
fix: lock runtime policies to utc3 and one worker
```

### Task 2: Vault cleanup invariant

**Files:**
- Modify: `main.py:1227-1338`
- Modify: `tests/test_session_send_no_otp.py`
- Modify: `tests/test_vault.py`

**Interfaces:**
- Consumes: `_decrypt_session(profile_id)` and `_encrypt_session(profile_id)`.
- Produces: `_with_client_unlocked(...)` always attempts encryption after decrypt.

- [ ] **Step 1: Write failing vault regressions**

Add tests where token validation fails immediately and where `_safe_stop`
raises. Both assert that `_encrypt_session(profile_id)` is still called and the
plaintext session is absent.

```python
with pytest.raises(RuntimeError, match="Сессия MAX отсутствует"):
    asyncio.run(m._with_client_unlocked(7, "+79990000000", callback))
encrypt.assert_called_once_with(7)
```

- [ ] **Step 2: Verify RED**

Run:
`python -m pytest tests/test_session_send_no_otp.py tests/test_vault.py -q --basetemp=.pytest-tmp/task2-red`

Expected: missing-token and stop-error tests FAIL because cleanup is bypassed.

- [ ] **Step 3: Implement nested cleanup**

Move all work after decrypt under one outer `try/finally`. Use nested
`try/finally` so stop failure cannot skip task cancellation, auth-state reset,
or `_encrypt_session(profile_id)`. Preserve the original operation error when
cleanup also fails and log the cleanup error.

- [ ] **Step 4: Verify GREEN and commit**

Run focused tests; expected PASS. Commit:

```text
fix: always reseal max sessions
```

### Task 3: Cancellation-safe queue claims

**Files:**
- Modify: `app/campaign_worker.py:253-460`
- Modify: `tests/test_inflight_groups.py`

**Interfaces:**
- Produces: each claimed job contains `queue_before: dict[str, object]`.
- Produces: `_restore_claim(job: dict[str, object], tracker: SendTracker) -> None`.

- [ ] **Step 1: Write failing queue tests**

Cover sequential and `random_norepeat` modes. Cancel after claim while
`SendTracker.may_requeue` is true and assert exact restoration of
`profile_idx`, `message_idx`, `group_idx`, and `message_bag`. Mark the tracker
unknown and assert no restoration.

- [ ] **Step 2: Verify RED**

Run:
`python -m pytest tests/test_inflight_groups.py -q --basetemp=.pytest-tmp/task3-red`

Expected: queue index and/or bag remain advanced.

- [ ] **Step 3: Implement minimal restoration**

Call `_claim_next_job_sync()` directly inside the existing async claim lock.
Capture the queue row before `_pick_next_message`. On safe cancellation or
definitely-unsent failure, restore the snapshot with one `UPDATE queue_state`.
Do not restore after `SEND_IN_FLIGHT`, `SEND_ACCEPTED`, or `SEND_UNKNOWN`.

- [ ] **Step 4: Verify GREEN and commit**

Run focused tests; expected PASS. Commit:

```text
fix: restore safely cancelled queue claims
```

### Task 4: Watchdog and scheduler lifecycle

**Files:**
- Modify: `app/campaign_worker.py:637-729`
- Modify: `tests/test_campaign_auto_run.py`

**Interfaces:**
- Watchdog restarts with `finish_status=None`, `record_campaign=False`.
- Scheduler disables a due row only after `start_worker(...) is True`.

- [ ] **Step 1: Write failing lifecycle tests**

Add a watchdog test asserting the running campaign is not finished and
`worker_restarts_total` increments after a successful restart. Add scheduler
tests asserting preflight/start failure leaves `enabled=1`, while successful
start changes it to `0`.

- [ ] **Step 2: Verify RED**

Run:
`python -m pytest tests/test_campaign_auto_run.py -q --basetemp=.pytest-tmp/task4-red`

Expected: watchdog uses `stopped`; scheduler consumes before validation.

- [ ] **Step 3: Implement lifecycle ordering**

Move schedule disable after a true start result. Preserve due schedules on
exceptions or missing prerequisites. Restart watchdog without finishing the
campaign and increment the existing metric only after start succeeds.

- [ ] **Step 4: Verify GREEN and commit**

Run focused tests; expected PASS. Commit:

```text
fix: preserve campaign lifecycle on restart
```

### Task 5: UTC+3 day accounting

**Files:**
- Modify: `main.py:2172-2183`
- Modify: `app/routes_dashboard.py:88-102`
- Modify: `static/js/index.js`
- Modify: `tests/test_ux_ops_backend.py`
- Modify: `tests/test_activity_log.py`

**Interfaces:**
- Produces: SQL local-day modifier `+3 hours` for `sent_at` and `now`.
- Produces: UI formatter renders naive SQLite UTC values as UTC+3.

- [ ] **Step 1: Write failing midnight tests**

Insert sends at `2026-08-25 21:30:00` UTC and evaluate at UTC+3 local date
`2026-08-26`. Assert quiet limits and dashboard include them in the 26 August
day. Add a static test requiring the UTC+3 formatter for send/activity rows.

- [ ] **Step 2: Verify RED**

Run:
`python -m pytest tests/test_ux_ops_backend.py tests/test_activity_log.py tests/test_saas_ux_static.py -q --basetemp=.pytest-tmp/task5-red`

Expected: dashboard uses UTC `date('now')` and display prints raw UTC.

- [ ] **Step 3: Implement UTC+3 boundaries**

Apply SQLite `date(sent_at, '+3 hours')` and `date('now', '+3 hours')` at all
daily log queries. Reuse one small JS formatting helper for operational times.

- [ ] **Step 4: Verify GREEN and commit**

Run focused tests; expected PASS. Commit:

```text
fix: align daily accounting to utc3
```

### Task 6: Phone and live-mutation safety

**Files:**
- Modify: `main.py:892-900`
- Modify: `app/routes_groups.py`
- Modify: `app/routes_profiles.py`
- Modify: `app/routes_admin.py`
- Modify: `tests/test_normalize_phone.py`
- Create: `tests/test_live_mutation_safety.py`

**Interfaces:**
- Produces: `_normalize_phone(phone: str) -> str` returning canonical
  `+<10..15 digits>` or raising `ValueError`.
- Produces: `_require_worker_idle() -> None` raising HTTP 409.

- [ ] **Step 1: Write failing boundary tests**

Test formatted Russian and international input, duplicate canonical forms,
letters, and short/long input. For every mutating group/profile route, install
an active worker task and assert HTTP 409 with no SQLite mutation.

- [ ] **Step 2: Verify RED**

Run:
`python -m pytest tests/test_normalize_phone.py tests/test_live_mutation_safety.py -q --basetemp=.pytest-tmp/task6-red`

Expected: invalid input is accepted and live routes mutate.

- [ ] **Step 3: Implement shared boundaries**

Normalize digits once in `_normalize_phone`; convert Russian `8` prefix only
for 11-digit input and reject anything outside 10..15 digits. Reuse one busy
guard in all user/admin mutation routes. For admin global disable, stop active
tenant workers before updating groups.

- [ ] **Step 4: Verify GREEN and commit**

Run focused tests; expected PASS. Commit:

```text
fix: validate phones and freeze live campaign data
```

### Task 7: Proxy validation and preflight

**Files:**
- Modify: `antiban_core.py:90-210`
- Modify: `main.py:2069-2155`
- Modify: `tests/test_group_proxy_server.py`
- Modify: `tests/test_wave2_high.py`

**Interfaces:**
- Produces: `check_proxy(raw, timeout=8.0, target_host="api.oneme.ru", target_port=443)`.
- Produces: bad-cache keys `(tenant_id, group_id, proxy_url)`.

- [ ] **Step 1: Write failing proxy tests**

Test invalid port `99999`, all pool members checked, tenant-separated cache,
SOCKS5 CONNECT request/reply, HTTPS TLS wrapping, and redacted errors.

- [ ] **Step 2: Verify RED**

Run:
`python -m pytest tests/test_group_proxy_server.py tests/test_wave2_high.py -q --basetemp=.pytest-tmp/task7-red`

Expected: invalid port escapes validation, preflight accepts first healthy URL,
and SOCKS stops after authentication.

- [ ] **Step 3: Implement full preflight**

Catch URL `ValueError`, validate host/port, and check every unique pool member.
Include tenant identity in cache keys. After SOCKS negotiation send a CONNECT
request for the MAX target and require a success reply. For HTTPS proxy URLs,
wrap the proxy socket using stdlib `ssl.create_default_context()` before HTTP
CONNECT. Never include password-bearing URLs in returned messages.

- [ ] **Step 4: Verify GREEN and commit**

Run focused tests; expected PASS. Commit:

```text
fix: validate every assigned proxy
```

### Task 8: Settings, message pool, and tenant recovery

**Files:**
- Modify: `app/routes_settings.py`
- Modify: `main.py:568-623`
- Modify: `app/tenant_init.py:61-69`
- Modify: `tests/test_global_pacing_settings.py`
- Modify: `tests/test_routes_panel.py`
- Modify: `tests/test_ux_ops_backend.py`
- Modify: `tests/test_register_rollback.py`

**Interfaces:**
- Produces: merged settings validation before any write.
- Produces: `_reset_all_tenants_queue_for_new_pool(n) -> list[int]` failed IDs.
- Produces: `init_tenant_db` always runs idempotent `init_db()`.

- [ ] **Step 1: Write failing storage tests**

Test a partial `delay_min_sec` update against a smaller stored max and expect
HTTP 400 with no write. Make one tenant reset raise and assert upload does
not report success silently. Pre-create an empty `app.db`, call
`init_tenant_db`, and assert required tables exist.

- [ ] **Step 2: Verify RED**

Run:
`python -m pytest tests/test_global_pacing_settings.py tests/test_routes_panel.py tests/test_ux_ops_backend.py tests/test_register_rollback.py -q --basetemp=.pytest-tmp/task8-red`

Expected: partial inversion persists, reset error is swallowed, empty DB stays
empty.

- [ ] **Step 3: Implement minimal storage fixes**

Merge only validated min/max pairs with current stored values before writing.
Remove the unused server `active.txt` mirror. Collect queue-reset failures and
raise one explicit error containing only tenant IDs. Always call idempotent
`init_db()` inside tenant scope.

- [ ] **Step 4: Verify GREEN and commit**

Run focused tests; expected PASS. Commit:

```text
fix: fail closed on partial storage updates
```

### Task 9: Mobile UI and final verification

**Files:**
- Modify: `static/index.html`
- Modify: `static/admin.html`
- Modify: `static/auth.html`
- Modify: `static/js/index.js`
- Modify: `static/js/admin.js`
- Modify: `tests/test_saas_ux_static.py`

**Interfaces:**
- Existing desktop table markup remains unchanged above 720 px.
- Mobile rows expose `data-label` values and display as stacked cards.

- [ ] **Step 1: Write failing responsive tests**

Require a 720 px media rule with card-row table behavior, `data-label`
generation in both renderers, 44 px interactive targets, viewport-safe modal
height, wrapped long identifiers, and absence of dead controls.

- [ ] **Step 2: Verify RED**

Run:
`python -m pytest tests/test_saas_ux_static.py -q --basetemp=.pytest-tmp/task9-red`

Expected: mobile tables still require horizontal scrolling and dead controls
remain.

- [ ] **Step 3: Implement responsive CSS/JS**

Add only CSS and renderer `data-label` attributes. Stack action groups, make
dialogs use `max-height: calc(100dvh - 2rem)` with internal scrolling, preserve
focus visibility/reduced motion, and keep every touch action at least 44 px.

- [ ] **Step 4: Verify UI**

Run static tests and `node --check` for all three JS files. Serve `static/`
locally and inspect index, admin, and auth pages at desktop and mobile widths
with the in-app browser. Confirm no page-level horizontal overflow.

- [ ] **Step 5: Full verification**

Run:

```text
python -m pytest -q --basetemp=.pytest-tmp/final
python -m pip check
python -m compileall -q main.py app tests
node --check static/js/index.js
node --check static/js/admin.js
node --check static/js/auth.js
git diff --check
git status --short
```

Expected: all runnable tests pass; only documented PostgreSQL/POSIX skips
remain; static checks exit 0.

- [ ] **Step 6: Commit**

```text
fix: optimize responsive campaign interfaces
```
