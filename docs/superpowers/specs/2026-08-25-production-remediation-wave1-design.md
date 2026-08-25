# MAX Sender production remediation — Wave 1 design

**Date:** 2026-08-25  
**Status:** Approved in chat  
**Scope:** Non-frozen production blockers only

## Goal

Remove the immediate duplicate-send, global message-pool race, subscription-expiry, and repository-hygiene blockers without changing anti-ban behavior, human behavior, role allocation, pacing rules, global settings, or `worker_pool_size`.

## Frozen boundaries

Wave 1 must not change:

- `antiban_core.py` behavior or role allocation;
- human timing, pauses, limits, windows, warmup, cooldown, or local-day rules;
- global pacing/settings validation or propagation;
- worker-pool policy;
- Git history or the already-deleted rule files;
- remote branches, deployment, production services, or credentials.

## Design

### 1. Fail closed for unsafe retry

`POST /api/campaign/retry_failed` returns HTTP 409 with a clear message that safe retry is temporarily unavailable. The existing rewind query and worker start are removed from the route. No database migration is introduced in Wave 1.

This deliberately removes an unsafe optional action. Normal campaign start/stop behavior remains unchanged. A full retry implementation, if later requested, requires campaign-scoped `send_log` identity and a persistent retry queue.

### 2. Serialize message-pool replacement against campaign starts

Add one process-wide async lock to the existing application runtime. Both global message upload and every worker start use this lock.

While holding the lock:

1. Upload checks whether any tenant worker is active.
2. If any worker is active, upload returns HTTP 409 and does not read/write the message pool or reset queues.
3. Otherwise the existing save/reset operation runs.
4. Worker start uses the same lock around its busy check and startup state transition, so a campaign cannot start between the upload check and pool replacement.

The application already enforces a single server process, so a process-local lock is sufficient for the supported deployment topology.

### 3. Make subscription expiry repeatable after renewal

During each lifecycle tick, entries in `_stopped_expired` whose subscription is active are removed before expired tenants are processed. A tenant can therefore be stopped again after a later expiry in the same process.

For subscription extension, lock the tenant row before reading subscription rows. The tenant row always exists, so concurrent first extensions serialize even when the subscriptions table is empty.

### 4. Remove generated audit artifacts

Delete only tracked `.audit-*` and `.pytest-tmp` test-output directories. Add those patterns to `.gitignore` and `.dockerignore`. Do not restore, modify, or delete rule/configuration files from the previous commit, and do not rewrite that commit.

## Error handling

- Unsafe retry: deterministic HTTP 409, no state mutation.
- Upload while any campaign runs: HTTP 409, no partial file/database/queue mutation.
- Failed message save: existing validation/error behavior remains.
- PostgreSQL extension: transaction rollback remains handled by the existing cursor context manager.
- Subscription lifecycle: existing outer tick error logging remains unchanged.

## Testing

Use TDD for each behavior:

1. A route test proves retry returns 409 and leaves queue/worker state unchanged.
2. Upload tests prove an active tenant blocks replacement and an idle system still saves normally.
3. A concurrency-focused unit test proves worker start and upload share the same lock boundary.
4. A lifecycle test proves renewal clears the stop latch and a later expiry stops again.
5. A PostgreSQL helper test proves `extend_subscription` locks the tenant row before subscription reads.
6. Run focused tests per task, then the full local suite, `pip check`, JS syntax checks, and `git diff --check`.

PostgreSQL, Docker, POSIX lock, dependency CVE, real MAX/proxy, and production deployment checks remain external release gates when unavailable locally.

## Delivery

Wave 1 is split into independent ownership areas:

- retry route;
- message-pool/start serialization;
- subscription lifecycle/PostgreSQL extension;
- generated-artifact cleanup.

No push or deployment is part of this design.
