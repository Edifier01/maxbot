# ADR 003: Worker Module Extraction (deferred)

**Status:** Deferred  
**Date:** 2026-07-30

## Context

Milestone 5 planned mechanical extraction of campaign worker loops from `main.py` (~4000 lines) into `app/campaign_worker.py` without behavior change.

During implementation, `git checkout main.py` accidentally reverted an uncommitted modern `main.py`. Recovery prioritized restoring REGISTRY/RUNTIME, tenant scope, and tests (42 passed).

## Decision

**Defer worker extraction** to a separate `/start-feature` after stable baseline is committed.

Worker orchestration remains in `main.py`. New Milestone 5 modules live alongside:

- `app/subscription_jobs.py` — expiry warnings, auto-stop worker
- `app/ops_monitor.py` — PG/Redis/circuit ops alerts
- `app/auth_rate_limit.py` — Redis-backed auth rate limit

## Consequences

- Positive: no campaign regression risk during recovery.
- Negative: `main.py` monolith remains; scoped edits only.
- Upgrade path: Feature Plan → extract `_worker_loop`, `_start_worker`, `_stop_worker` block when git baseline is safe.
