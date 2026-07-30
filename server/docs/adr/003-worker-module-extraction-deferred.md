# ADR 003: Worker Module Extraction

**Status:** Accepted (phase 1)  
**Date:** 2026-07-30 (deferred) · **Implemented:** 2026-07-30

## Context

Milestone 5 planned mechanical extraction of campaign worker loops from `main.py` (~4000 lines) into `app/campaign_worker.py` without behavior change.

During Milestone 5 implementation, `git checkout main.py` accidentally reverted an uncommitted modern `main.py`. Recovery prioritized restoring REGISTRY/RUNTIME, tenant scope, and tests (42 passed). Extraction was deferred until a stable baseline existed.

## Decision

**Phase 1 (accepted):** Extract worker orchestration into `app/campaign_worker.py` using a lazy `import main as m` bridge. No pacing, send, or antiban logic moves in this phase.

Extracted symbols:

- Campaign lifecycle: `worker_shutdown`, `begin_campaign`, `finish_campaign`, `notify_campaign_end`
- Telegram helpers: `schedule_telegram`, `telegram_notify`, …
- Worker loops: `claim_next_job`, `worker_loop`, `pool_worker_loop`, `pool_supervisor`
- Process loops: `scheduler_loop`, `watchdog_loop`
- Control: `start_worker`, `stop_worker`, `stop_all_workers`

`main.py` re-exports via `from app.campaign_worker import … as _start_worker` so existing `import main as m` callers unchanged.

Mechanical tooling: `scripts/extract_worker.py`, `scripts/patch_main_worker.py`.

## Consequences

- Positive: ~780 lines removed from `main.py`; worker domain has a named module; pytest baseline unchanged (44 passed).
- Negative: circular dependency via lazy `_m()` bridge; send/pacing still in `main.py`.
- Phase 2 (future `/start-feature`): move `_send_with_retry` and pacing helpers; replace lazy bridge with explicit deps.

## Validation

```
MAX_TEST=1 MAX_SERVER_MODE=1 JWT_SECRET=test-secret-min-32-chars-long python -m pytest tests/ -q
→ 44 passed, 4 skipped
```
