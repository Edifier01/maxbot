---
name: celery-parity
description: Keeps in-process campaign workers and optional Celery profile behavior aligned. Use when touching celery_worker, USE_CELERY, or campaign start enqueue.
---

# Celery Parity

## Purpose

Prevent divergent bugs between default asyncio workers and `USE_CELERY=1` path.

## When To Use

- Editing `celery_worker.py`, compose celery profile, campaign start/schedule via `INTERNAL_SERVICE_TOKEN`

## Workflow

1. Read PRODUCTION-OPS Celery section and `tests/test_celery_worker.py`.
2. Celery tasks that call HTTP must pass tenant identity headers correctly.
3. Keep env requirements (`INTERNAL_SERVICE_TOKEN`, Redis URL) consistent with app.
4. Default remains in-process (`USE_CELERY=0`); Celery is optional scale path.
5. Run celery unit tests; note compose profile smoke when ops changes.

## Validation Checklist

- [ ] Tenant id propagation intact
- [ ] Token auth not weakened
- [ ] Tests updated

## Related Agents

- `campaign-antiban`, `devops-automator`, `identity-access`
