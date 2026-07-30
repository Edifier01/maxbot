# ADR 001: Tenant Worker Isolation

**Status:** Accepted  
**Date:** 2026-07-30

## Context

MAX Sender Server is multi-tenant SaaS. Each tenant has isolated SQLite under `data/tenants/{id}/`. Campaign workers run as asyncio tasks that outlive the HTTP request. After `ServerAuthMiddleware` calls `clear_context()`, worker loops lost tenant ContextVar and accessed `root/data` instead of tenant data.

A single global `RUNTIME.worker_task` allowed one campaign for the entire process — unacceptable when scaling to many users with many groups and accounts.

## Decision

1. **Per-tenant worker runtime** — `RuntimeRegistry` holds `CampaignRuntime` keyed by `tenant_id` (key `0` for local/desktop).
2. **Context snapshot on worker start** — `_start_worker` captures `snapshot_context()` and restores it for the entire worker task lifetime.
3. **One active campaign per tenant** — each tenant has independent `worker_task`, `worker_lock`, pacing dicts.
4. **Global app runtime** — watchdog, scheduler, backup, `shutting_down` remain process-wide; scheduler/watchdog iterate tenants.
5. **Startup reset** — `_reset_auth_on_startup` resets `running` campaigns in all tenant SQLite DBs under `data/tenants/*/app.db`.
6. **Phase 3 (2026-07-30):** Celery jobs pass `X-Tenant-Id`; WS uses JWT `?token=` in server mode; settings/messages use tenant SQLite (option A — no migration from global).

## Consequences

- Positive: tenant A campaign cannot stop or corrupt tenant B data.
- Positive: multiple tenants can run campaigns concurrently (subject to VPS resources).
- Negative: memory scales with active tenant worker state (pacing dicts per tenant).
- Negative: scheduler/watchdog loops iterate all tenant dirs — O(tenants); acceptable until hundreds of tenants.

## Alternatives Considered

- **ContextVar only without registry** — insufficient; worker task loses context after request.
- **Single queue service** — deferred; current asyncio worker retained with tenant binding.
