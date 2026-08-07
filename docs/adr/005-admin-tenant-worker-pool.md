# ADR 005: Admin-only per-tenant worker pool size

**Status:** Accepted (2026-08-07)  
**Feature:** FEATURE-SAAS-UX-2026  
**Related:** ADR 001 (tenant worker isolation), ADR 002 (pacing at scale)

## Context

`worker_pool_size` controls parallel send workers within one tenant. Default `1` is safest for anti-ban (ADR 002). Tenants should not self-raise parallelism; only operators/admins may tune per institution.

## Decision

1. Default `worker_pool_size = 1` in `main.DEFAULTS` for all tenants.
2. **Admin-only** per-tenant API:
   - `GET /api/admin/tenants/{tenant_id}/settings` → `{ worker_pool_size }`
   - `PUT /api/admin/tenants/{tenant_id}/settings` → `{ worker_pool_size: 1..32 }`
3. Regular users: `worker_pool_size` **stripped** on `PUT /api/settings`.
4. Admins may still set global pool via `PUT /api/settings` when in admin context.
5. If tenant worker is running and size changes → stop + restart worker in `tenant_scope`.

## Consequences

- Parallel workers remain isolated per tenant via `REGISTRY.worker_for(tenant_id)` (ADR 001).
- Admin UI (Round 3) consumes these endpoints; tenant Settings tab should hide pool control for users.
- Raising pool size increases ban risk — admin UI should surface ADR 002 guidance.

## Implementation

- `app/routes_admin.py` — GET/PUT tenant settings
- `app/routes_settings.py` — strip for non-admin
- `tests/test_admin_tenant_settings.py`, e2e in `test_e2e_server.py`
