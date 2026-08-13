# ADR 007: Global pacing settings apply to tenant workers via copy

**Status:** Accepted  
**Date:** 2026-08-13  
**Feature:** FEATURE-UX-OPS-2026  
**Related:** ADR 001 (tenant worker isolation), ADR 002 (pacing at scale), ADR 005 (per-tenant worker pool)

## Context

Admin «Настройки рассылки» (`PUT /api/settings` as a non-impersonating admin) is bound by `ServerAuthMiddleware` to `use_global_data=True` and therefore writes **global** SQLite (`data/global/app.db`). Campaign workers run in tenant scope (ADR 001) and read **tenant** SQLite (`data/tenants/{id}/app.db`). Tenant DBs are seeded from `DEFAULTS` on `init_db`. The admin tab was a placebo: saving delays/limits never changed what workers used.

Message pool is already global in server mode (`load_message_pool` / `save_messages_file` use `_global_conn()`). That path stays as-is.

## Decision

1. **Allowlisted copy on admin save** — after a non-impersonating admin `PUT /api/settings` writes global SQLite, copy **only** pacing/antiban keys from that request into every tenant SQLite `settings` table and invalidate the per-tenant settings cache.
2. **Seed on new tenant** — `init_db` for a fresh tenant DB (`settings` empty, tenant context, not global) copies current global allowlisted values when present; otherwise `DEFAULTS`.
3. **Allowlist only** — never copy secrets or per-tenant ops: `api_pin`, `telegram_bot_token`, `telegram_chat_id`, `webhook_url`, `auto_run`, `auto_run_pool_reset_day`, `worker_pool_size`, `backup_interval_hours`, `password_max_attempts`. `worker_pool_size` remains per-tenant via the existing admin tenant settings API (ADR 005).
4. **Isolation unchanged** — each tenant still has its own SQLite file under `data/tenants/{id}/`. Copy is a one-way fan-out of allowlisted keys from global; tenant-unique keys (webhooks, PIN, pool size, `auto_run`) are not written into other tenants.
5. **Messages stay global** — TXT / `message_pool` remain in global sqlite (existing). This ADR does not move the pool into tenant DBs.

## Consequences

- Positive: admin pacing changes are what tenant workers actually read via `get_setting`.
- Positive: new institutions inherit current global pacing instead of stale `DEFAULTS` when global has been tuned.
- Negative: fan-out is O(tenants × keys) on each admin save; acceptable until hundreds of tenants (same bound as ADR 001 watchdog iteration).
- Residual: a tenant that customized an allowlisted key (if any path wrote it locally) will be overwritten on the next global save. Product intent is global admin as source of truth for pacing.

## Out of scope

- Expanding institution (`role=user`) settings capabilities
- Copying `auto_run` / pause state across tenants
- Changing message-pool storage
- Per-tenant overrides of delay keys

## Alternatives Considered

- **Workers read global settings directly** — rejected; mixes scopes and breaks ADR 001 “settings use tenant SQLite”. Cache/scope bugs would be easy to reintroduce.
- **Blacklist copy (copy DEFAULTS minus secrets)** — rejected; new keys would copy by default. Explicit allowlist fails closed.
- **Single shared settings table in PostgreSQL** — rejected; hybrid PG + per-tenant SQLite is the current architecture; no schema ADR for this feature.
