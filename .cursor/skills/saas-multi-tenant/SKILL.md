---
name: saas-multi-tenant
description: Multi-tenant SaaS isolation principles adapted for MAX Sender (JWT tenant context + per-tenant SQLite). Use with tenant-isolation-max; do not apply upstream TS/RLS/Prisma recipes literally.
---

# SaaS Multi-Tenant (Adapted for MAX Sender)

> Source: AAS `saas-multi-tenant` — **heavily adapted**. Upstream assumes TypeScript, PostgreSQL RLS, Prisma/Drizzle. MAX Sender uses PostgreSQL for SaaS meta + **SQLite per tenant** + ContextVar middleware.

## Purpose

Apply sound multi-tenant principles without forcing RLS/ORM rewrites.

## When To Use

- Designing or reviewing tenant-scoped features, admin cross-tenant access, subscription gating

## When Not To Use

- As a greenfield scaffold to replace existing `app/tenant*.py` / middleware
- Prefer `tenant-isolation-max` for concrete file/path/worker rules

## Principles To Keep

1. Tenant id from authenticated context, never from untrusted client input for authz.
2. Every operational query/path must be tenant-scoped.
3. Admin/impersonation is an explicit elevated path with auditability.
4. Defense in depth: middleware + data-layer scoping + tests.
5. Fail closed on missing tenant context in server mode.

## MAX Sender Mapping

| Upstream idea | MAX Sender equivalent |
|---------------|----------------------|
| Shared-schema RLS | SaaS tables in PG with `tenant_id`; ops data in SQLite files per tenant |
| `SET LOCAL app.current_tenant_id` | ContextVar set by `ServerAuthMiddleware` |
| ORM global filters | Explicit tenant paths + helpers in `app/` |
| Admin cross-tenant | Admin routes + impersonation JWT claims |

## Workflow

1. Read HOW-IT-WORKS isolation + ADR 001.
2. Apply principles above to the Feature Plan.
3. Implement via existing modules; add cross-tenant tests.
4. Do **not** introduce Prisma/RLS unless ADR approved.

## Validation Checklist

- [ ] No client-trusted tenant id for authz
- [ ] Cross-tenant tests considered
- [ ] Paired with `tenant-isolation-max` for code changes

## Related Agents

- `identity-access`, `appsec-engineer`, `database-reliability`

## Related Rules

- `tenant-isolation.mdc`
