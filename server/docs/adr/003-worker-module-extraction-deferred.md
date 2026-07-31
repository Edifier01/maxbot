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
**Phase 2 (implemented 2026-07-31):** `app/campaign_send.py` holds `send_with_retry`, `sleep_send_delay`, pacing; `app/campaign_facade.py` replaces lazy `_m()` with explicit `main` proxy; `campaign_worker.py` has zero `_m()` calls.

**Phase 3 (implemented 2026-07-31):** Mechanical extraction to:
- `app/sqlite_backend.py` — `_conn`, `init_db`, schema migrations
- `app/campaign_queue.py` — message bag + `_pick_next_message`
- `app/campaign_query.py` — `_active_groups`, `_active_profiles_for_group`, `_ensure_group_role_plan`

`main.py` re-exports all symbols; callers via `app.runtime.main` unchanged.

## Validation

```
MAX_TEST=1 MAX_SERVER_MODE=1 JWT_SECRET=test-secret-min-32-chars-long python -m pytest tests/ -q
→ 64 passed, 4 skipped (phase 3)
```
