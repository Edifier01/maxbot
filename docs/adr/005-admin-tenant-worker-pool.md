# ADR 005: Fixed per-tenant campaign owner

**Status:** Accepted (2026-08-07)  
**Feature:** FEATURE-SAAS-UX-2026  
**Related:** ADR 001 (tenant worker isolation), ADR 002 (pacing at scale)

## Context

`worker_pool_size` was previously considered an admin-tunable parallelism
setting. The production-safety remediation fixed the campaign owner to one
worker per tenant so that the operation ledger, Stop fence and recovery hold
have one unambiguous owner.

## Decision

1. `worker_pool_size = 1` is fixed in `main.DEFAULTS` and the runtime pool-size policy.
2. Admin and tenant settings APIs expose the value for observability only and accept only `1`.
3. `.env` and Compose examples must pass `1`; they do not provide a parallelism override.
4. Celery remains trigger-only and does not create a second campaign owner.

## Consequences

- Each tenant has one `REGISTRY.worker_for(tenant_id)` campaign owner (ADR 001).
- The settings UI does not expose a pool-size control; the fixed value can be shown as policy state.
- Removing parallelism avoids split-brain ledger ownership and makes recovery/stop behavior auditable.

## Implementation

- `app/routes_admin.py` — fixed `Literal[1]` tenant setting
- `app/routes_settings.py` — fixed policy fan-out
- `tests/test_admin_tenant_settings.py`, `tests/test_no_artificial_presence.py`, e2e in `test_e2e_server.py`
