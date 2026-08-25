# MAX Sender production readiness — stages 1–3 design

**Date:** 2026-08-25  
**Status:** Approved in chat  
**Scope:** Release boundaries, current delta audit, and CI evidence

## Goal

Reach the last safe gate before Linux staging by documenting the exact release
contract, closing non-frozen production blockers, and obtaining reproducible CI
evidence for the exact release commit.

## Frozen boundaries

Stages 1–3 must not change:

- anti-ban behavior or `antiban_core.py` behavior;
- human timing, pauses, limits, windows, warmup, cooldown, role allocation, or
  local-day rule semantics;
- global settings, their defaults, validation, or propagation;
- `worker_pool_size` behavior or policy;
- production credentials, external services, shared remote branches, or the
  production host without a separate release approval.

Test-only isolation fixes are permitted when they do not change production
behavior. CI and deployment workflow changes are permitted only when they add
verification or fail closed; they must not change application rules.

## Current evidence

- Branch baseline: `main` at `16d0ce0`, clean, eleven commits ahead of
  `origin/main` when the worktree was created.
- Prior merged verification: 267 passed and 20 skipped.
- Fresh isolated baseline: 266 passed, 20 skipped, one order-dependent failure.
- The failure reproduces only after `tests/test_campaign_modules.py` because
  `tests/test_flood_wait.py` changes `MAX_SERVER_MODE` after `app.config` has
  already cached it. The test must patch the existing `_is_server_mode` boundary;
  the flood-wait production path passes alone.
- PostgreSQL, POSIX locking, Docker/Linux, dependency scanning, and external
  MAX/proxy behavior are not proven locally on this Windows host.

## Design

### 1. Release contract and ledger

Create one current production-readiness ledger. Re-evaluate every P1 from the
2026-08-21 audit against current code and tests. Each item is `CLOSED`, `OPEN`,
or `BLOCKED BY FROZEN SCOPE`, with exact evidence and a release gate.

The ledger also records environmental facts that cannot be proven from the
repository: target host, domain, CPU/RAM, production `.env`, secrets, DNS, and
access to a Docker-capable Linux environment. Unknown facts remain explicit
NO-GO gates; no placeholder is treated as evidence.

### 2. Minimal non-frozen remediation

Fix only confirmed blockers outside the frozen boundaries. Every behavior fix
uses a failing test first. The known baseline contamination is corrected in
test setup only; campaign sending and flood-wait behavior stay intact.

If an audit finding crosses the frozen boundary, record it rather than editing
it. In particular, role-percentage application and UTC/local-day rule behavior
remain untouched.

### 3. CI and deploy evidence

The normal CI workflow must prove the locked Python dependencies, SQLite suite,
PostgreSQL suites, POSIX-only lock behavior, Compose configuration, dependency
audit, and backup/restore smoke test.

The manual deployment workflow must verify the same release commit before any
SSH deployment. Deployment remains manual and immutable by SHA. Verification
must fail closed when required database or external HTTPS checks are absent;
no production deployment is performed in stages 1–3.

### 4. Release boundary

Stages 1–3 stop before external side effects. Push to `origin`, GitHub Actions,
VPS access, live MAX/proxy canaries, production backup, and deployment each need
the separate approval already defined in the release plan.

## Testing

- Reproduce every discovered failure before changing code.
- Run focused tests after each minimal fix.
- Run the complete local suite after all local changes.
- Run `pip check`, JavaScript syntax checks, workflow/static checks, and
  `git diff --check`.
- Record local skips honestly; GitHub/Linux evidence cannot be inferred from a
  Windows pass.

## Delivery

Stages 1–3 produce:

1. a current release ledger;
2. reviewed commits for confirmed non-frozen blockers;
3. CI/deploy verification changes required by the ledger;
4. a final pre-push GO/NO-GO report for the exact branch SHA.

No push or deployment is included.
