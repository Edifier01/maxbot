# Feature Plan — SaaS UX Completion (2026-08-07)

**Status:** COMPLETE (2026-08-07) — verifier PASS  
**Zone:** `server`  
**Complexity:** HIGH

## Vision (locked)

User panel:
- Register without subscription → groups/accounts OK, **no campaign start**
- Header: subscription active until date / «подписка не оформлена»
- Start without sub → message «для использования бота оформите подписку»
- Account badges in group list: **активен | неактивен | забанен**
- Start/Stop clickable; main screen shows sending active/stopped
- Any **banned** account during send → stop **all** tenant sending
- Fix summary; move to main campaign screen; remove «Сводка» tab

Admin panel:
- Per-tenant `worker_pool_size` (admin-only; default **1** for all)
- Global «Настройки рассылки» + «Сообщения (пул)» sections on main admin screen
- Fix delete user button

## Product decisions (Ed, 2026-08-07)

| # | Decision |
|---|----------|
| D1 | Explicit `profiles.status = 'banned'` in per-tenant SQLite (not UI heuristic only) |
| D2 | Users **cannot** send without subscription; message pool loaded **only by admin** (current model kept) |
| D3 | Admin settings/messages sections = **global** pool (not per-tenant inline) |
| D4 | Default `worker_pool_size = 1` for all tenants; **only admin** may change per user |

## ADR required

- **ADR-004 (draft):** Ban detection → set `status=banned` → `stop_worker(tenant_id)` + `auto_run=0`; distinguish ban from recoverable errors
- **ADR-005 (draft):** Admin-only per-tenant `worker_pool_size`; tenant workers isolated via existing REGISTRY (ADR 001)

## Agent Assignment

| Agent | Task |
|-------|------|
| database-engineer | Add `banned` to ProfileStatus + SQLite migration; review delete order |
| campaign-specialist | Ban error taxonomy; stop-all policy |
| backend-engineer | Ban persist + stop worker; admin worker API; dashboard/status fixes |
| frontend-engineer | User UI: badges, subscribe dialog, summary merge, start/stop status |
| frontend-engineer | Admin UI: global settings/messages sections, per-user workers, delete fix |
| security-engineer | Subscription gate, admin APIs, delete tenant |
| qa-engineer | E2E + unit tests |
| verifier | Final gate |

## Skills

`maxserver-fastapi-backend`, `maxserver-static-ui`, `maxserver-campaign`, `maxserver-auth-security`, `tenant-isolation-max`, `maxserver-postgresql`, `maxserver-testing`, `antiban-campaign-safety`

## Execution rounds

### Round 1 (parallel)
- database-engineer: `banned` status + migration
- campaign-specialist + backend-engineer: ban detect → persist → stop tenant worker
- backend-engineer: `PUT/GET /api/admin/tenants/{id}/settings` (`worker_pool_size` 1–32, admin-only)
- security-engineer + database-engineer: delete user hardening

### Round 2
- frontend-engineer: user panel (header, subscribe on start, badges, summary on main, remove Сводка)

### Round 3
- frontend-engineer: admin panel (global settings/messages sections, per-user worker input, delete button)

### Round 4
- qa-engineer → verifier

## Verification

```bash
MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/ -q
MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/test_e2e_server.py -q
```

Manual: vision checklist (8 items from Feature Plan).

## Out of scope

- User self-upload of message pool
- Desktop mirror (server-only feature)
- Payment gateway / self-service subscription purchase
