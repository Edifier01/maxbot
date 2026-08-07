---
name: tenant-isolation-max
description: Enforces MAX Sender multi-tenant isolation via ContextVar, data/tenants/{id}/ paths, and cross-tenant tests. Use when touching tenant context, paths, workers, or shared APIs.
---

# Tenant Isolation (MAX Sender)

## Purpose

Prevent cross-tenant data leaks in the hybrid PG + per-tenant SQLite architecture.

## When To Use

- Changes to middleware, tenant paths, workers, SQLite backends, admin impersonation
- Any API that reads/writes tenant operational data

## When Not To Use

- Pure SaaS PG user admin with no tenant filesystem touch (still consider `saas-multi-tenant` principles)

## Required Inputs

- Feature Plan scope; ADR 001

## Workflow

1. Read `docs/adr/001-tenant-worker-isolation.md` and HOW-IT-WORKS isolation section.
2. Ensure tenant id comes from authenticated context — never trust client-supplied tenant id for authorization.
3. Keep worker tasks bound to tenant snapshot/registry (no lost ContextVar after request end).
4. Paths must resolve under `data/tenants/{id}/` in server mode.
5. Add/keep tests: `tests/test_cross_tenant_api.py`, `test_tenant_isolation_sqlite.py`, `test_tenant_scope.py` as relevant.
6. Admin impersonation must not leave sticky context across requests.

## Validation Checklist

- [ ] No cross-tenant path/DB access
- [ ] Worker/context lifecycle respected
- [ ] Relevant isolation tests pass

## Related Agents

- `identity-access`, `appsec-engineer`, `database-reliability`, `campaign-antiban`

## Related Rules

- `tenant-isolation.mdc`
