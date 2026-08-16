---
name: maxserver-campaign
description: MAX Sender campaign pacing, warmup, pause/resume, and unofficial MAX send safety. Use when changing workers, delays, queues, or send/presence client flow.
---

# MAX Sender Campaign

Compose (task-scoped): `antiban-campaign-safety`, `celery-parity`. This file wins on product gates.

## ADRs (read if the change touches that area)

- 001 tenant worker isolation
- 002 campaign scale / pacing
- 004 ban → stop tenant campaign
- 005 admin tenant worker pool
- 007 global pacing settings copy to tenants

## Code map

`app/campaign_*.py`, `app/hooks.py`, `antiban_core.py` (if present), optional `celery_worker.py`.

## Non-negotiable

- Do not remove or silently weaken pacing, warmup, delay floors, or circuit breakers without Feature Plan + user approval.
- Default workers are in-process; `USE_CELERY=1` must keep tenant identity headers (`INTERNAL_SERVICE_TOKEN`).
- Send/presence must not request MAX SMS/OTP (`login_mode=False` / session-only). Missing session fails closed.
- Per-tenant worker isolation (ADR 001) stays intact.

## Verify

`tests/test_campaign_modules.py` and any worker/tenant runtime tests you touched. Manual: pause holds, start/stop, ban-stop if relevant.
