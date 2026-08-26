# MAX Sender audit remediation and mobile UI design

**Date:** 2026-08-26  
**Status:** Approved in chat  
**Branch:** `codex/audit-remediation-mobile`

## Goal

Fix the confirmed queue, session-vault, worker lifecycle, proxy, validation,
scheduler, settings, tenant-initialization, and UI defects from the read-only
audit without changing the product's fixed-third role policy or adding a new
queue system.

## Product decisions

- Operational local time is fixed at UTC+3. Database timestamps remain UTC;
  local-day limits, dashboard totals, schedules, and displayed operational
  times use UTC+3 consistently.
- Rotation roles remain fixed thirds. Percentage controls and other settings
  that imply configurable role shares are removed from the UI/API surface.
- The supported deployment uses one campaign worker per tenant. The effective
  `worker_pool_size` is fixed to `1`; controls that suggest higher safe
  concurrency are removed.
- Safe retry of failed sends remains unavailable. The fail-closed HTTP 409
  endpoint stays for compatibility; the misleading UI action is removed.
- No dependency, durable queue subsystem, deployment, live MAX send, or live
  proxy operation is introduced by this work.

## Design

### 1. Cancellation-safe queue claims

The existing SQLite claim is short and the supported pool size is one. Run the
synchronous claim while holding the existing claim lock instead of handing it
to an uncancellable background thread. The claim returns an exact snapshot of
the pre-claim queue indices and random-message bag.

If cancellation or a definitely-unsent terminal failure occurs before MAX
accepts the message, restore that snapshot in one SQLite transaction. If the
send entered the network or its outcome is unknown, keep the existing
fail-closed behavior: persist `unknown` and never requeue automatically.

This fixes message loss without adding leases, a job table, or a second queue.
The one-worker policy makes snapshot restoration unambiguous.

### 2. Session-vault invariant

Once `session.db.enc` is decrypted, one outer `try/finally` owns all remaining
setup, token checks, client construction, execution, and cleanup. Cleanup uses
nested `finally` blocks so client-stop failure cannot skip task cancellation or
session encryption. The invariant after every return, exception, timeout, or
cancellation is: plaintext `session.db` is absent when an encrypted session
exists.

### 3. Worker lifecycle and campaign accounting

- Clamp the effective pool size to one in the backend and reject/remove UI
  attempts to configure a larger value.
- A watchdog restart stops the worker with `finish_status=None`, preserving the
  active campaign row, then resumes with `record_campaign=False`.
- Increment the existing restart metric only after a successful restart.
- User stop/pause still closes the campaign with its explicit status.

### 4. Fixed UTC+3 and fixed-third roles

- Use one fixed UTC+3 offset for `_local_now`, `_local_today`, send-window and
  daily-limit calculations.
- SQLite daily queries apply `+3 hours` to both `sent_at` and `now`.
- API/UI operational timestamps are rendered as UTC+3, while JWT,
  subscriptions, and stored audit timestamps remain UTC internally.
- Runtime role assignment continues to use the existing fixed-third allocator.
  Remove percentage, role min/max, timezone-offset, and worker-pool controls
  from the settings pages so the panel reflects real behavior.

### 5. Input and live-mutation safety

- Canonicalize phones to E.164-like `+<10..15 digits>`. Russian `8XXXXXXXXXX`
  becomes `+7XXXXXXXXXX`; punctuation is removed, letters and invalid lengths
  are rejected. Single and bulk routes use the same normalizer.
- Any group/profile create, update, unlink, or delete that can change an active
  campaign returns HTTP 409 while that tenant worker is running.
- Global admin "disable all groups" first stops affected workers, then updates
  groups. Other admin tenant mutations use the same busy guard.

### 6. Proxy correctness

- Validate scheme, hostname, credentials, and port at the request boundary;
  malformed or out-of-range ports produce HTTP 422/400, never HTTP 500.
- Campaign preflight checks every unique proxy in each group pool, not only the
  first healthy URL.
- The bad-proxy cache key includes tenant identity, group ID, and proxy URL.
- SOCKS5 validation performs authentication when required and a CONNECT to the
  MAX target host/port. HTTPS proxies use TLS to the proxy before CONNECT.
- A campaign fails closed if any proxy that can be assigned is unusable.

### 7. Scheduler, settings, messages, and tenant recovery

- A due schedule is disabled only after `start_worker` reports success.
  Transient vault, proxy, pool, profile, or subscription failures keep the due
  schedule available for a later tick.
- Before persisting partial settings, merge them with stored values and reject
  every resulting min/max inversion. Existing full-form updates remain valid.
- Server message upload uses the global SQLite pool as its single source of
  truth; the unused `active.txt` mirror is removed. Tenant queue-reset failures
  are collected and returned explicitly instead of being swallowed.
- `init_tenant_db` always runs idempotent migrations. An existing empty SQLite
  file is repaired instead of being treated as initialized.

### 8. Mobile UI

Keep the existing visual language and desktop layout. At widths up to 720 px:

- keep navigation horizontally scrollable with clear active-state visibility;
- stack campaign controls and settings without clipped inline widths;
- render wide data tables as readable row cards where practical, retaining
  semantic table markup for desktop;
- keep destructive actions separate from primary actions;
- guarantee 44 px touch targets, viewport-safe dialogs, wrapped identifiers,
  and no page-level horizontal overflow;
- remove dead retry, timezone, role-share, and worker-pool controls.

No frontend framework or dependency is added. CSS and the existing vanilla JS
renderers are sufficient.

## Error handling

- Queue restoration happens only when the send is proven not started.
- Unknown network outcomes remain non-retriable to prevent duplicates.
- Vault cleanup errors are logged, but encryption is still attempted.
- Busy campaign mutations return HTTP 409 with an instruction to stop first.
- Proxy validation reports the specific pool member and reason without
  exposing credentials.
- Schedule failure leaves the schedule enabled and records the reason.
- Message-pool reset returns explicit failed tenant IDs; it never reports full
  success after a swallowed reset error.

## Testing

Use TDD for each behavior:

1. Claim cancellation restores sequential indices and random bag; an unknown
   send is not restored.
2. Missing token, client-construction failure, stop failure, timeout, and task
   cancellation all leave the vault encrypted.
3. Pool size is always one; watchdog preserves campaign history and increments
   its metric after restart.
4. UTC+3 boundary tests cover local midnight and dashboard totals; role tests
   continue to prove fixed thirds.
5. Phone tests cover Russian formatting, international numbers, duplicate
   canonical forms, letters, and invalid lengths.
6. Live mutation routes return 409; global admin disable stops workers first.
7. Proxy tests cover every pool member, tenant-scoped cache keys, invalid ports,
   SOCKS CONNECT, and credential redaction.
8. Scheduler tests prove failure retains and success consumes the schedule.
9. Partial settings tests merge stored values; empty tenant DB migration and
   queue-reset error reporting have regressions.
10. Static UI tests cover removed controls, responsive rules, touch targets,
    overflow, and table-card labels.

The full suite must also run from a clean initialized worktree. The discovered
flood-wait order dependency is isolated as part of the test bootstrap rather
than hidden by copying the user's ignored `data/` directory.

Final verification includes the full pytest suite, focused PostgreSQL tests
when infrastructure is available, `pip check`, Python compilation, JavaScript
syntax checks, `git diff --check`, and desktop/mobile browser inspection.

## Release boundaries

This work does not authorize a push, deploy, production service change, live
MAX message, or live proxy check. PostgreSQL integration, Docker/Redis,
real MAX/proxy behavior, backup/restore, and production CI remain separate
release gates when they are unavailable locally.

