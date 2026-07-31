# Tasks

## Epic: Mobile UI + Admin bulk groups

Status: COMPLETED  
Owner: frontend + backend

Tasks:
- [x] Mobile CSS: index.html, auth.html, admin.html (@media 720px)
- [x] POST /api/admin/groups/activate-all & deactivate-all
- [x] admin.html: global buttons + confirm
- [x] tests/test_admin_groups_bulk.py

Validation:
- [x] pytest 2 passed (admin bulk) + role rotation suite

---

## Epic: Role Rotation 33/33/33 (ordered 3-day cycle)

Status: COMPLETED  
Owner: backend-engineer + campaign-specialist

Tasks:
- [x] `antiban_core.split_thirds` + `assign_rotation_roles` (remainder → first parts)
- [x] `_ensure_group_role_plan` — порядок `order_index`, без shuffle
- [x] `role_cycle_anchor` — первый старт кампании, без сброса
- [x] `_role_cycle_day()` от якоря; части со сдвигом active/quiet/skip
- [x] `tests/test_role_rotation.py`
- [x] UI hint в `static/index.html`

Validation:
- [x] pytest 11 passed (role rotation + legacy percent split)

---

## Epic: Main.py Monolith Split (P3-3)

Status: COMPLETED  
Owner: backend-engineer

Tasks:
- [x] app/sqlite_backend.py — conn pool, init_db, migrations
- [x] app/campaign_queue.py — message bag, pick
- [x] app/campaign_query.py — active groups/profiles, role plan
- [x] main.py re-exports; ADR 003 phase 3

Validation:
- [x] pytest 64 passed, 4 skipped

---

## Epic: Code Review Fixes 2026-07-31

Status: COMPLETED  
Owner: backend + database + security + devops + campaign

Tasks:
- [x] P0-1..P0-3: middleware, ops_monitor, auth_rate_limit
- [x] P1-1..P1-5: db pool, tenant_init, vault UI, scheduler PG, POSTGRES_PASSWORD
- [x] P2/P3/M: requirements-server, pool timeout, telegram unify, /me, migrations, cleanup
- [x] P2-5: `import main` → `app.runtime` proxy (17 files)
- [x] P3-3: sqlite_backend, campaign_queue, campaign_query extraction

Validation:
- [x] pytest 64 passed, 4 skipped

---

## Epic: Agent Review — Security Tail

Status: COMPLETED  
Owner: security + backend + frontend

Tasks:
- [x] FIX-007: token_version migration + bump on tenant delete
- [x] FIX-008: /metrics INTERNAL_SERVICE_TOKEN only
- [x] FIX-009: WebSocket first-message auth + index.html

Validation:
- [x] pytest 61 passed, 4 skipped

---

## Epic: Worker Monolith Refactor

Status: COMPLETED (phase 1 + phase 2)  
Owner: backend-engineer  
Scope: mechanical extraction → `app/campaign_worker.py`, lazy main bridge

Tasks:
- [x] Update extract/patch scripts with current line ranges
- [x] Generate `app/campaign_worker.py` (~780 lines)
- [x] Patch `main.py` imports (re-export `_start_worker`, etc.)
- [x] Fix `test_worker_tenant_runtime` patch target
- [x] ADR 003 → Accepted (phase 1)
- [x] Phase 2: decouple lazy `_m()` bridge, move send/pacing → `app/campaign_send.py` + `app/campaign_facade.py`

Validation:
- [x] pytest 44 passed, 4 skipped

---

## Epic: Milestone 5 — Production Readiness

Status: COMPLETED  
Owner: backend + frontend + devops

Tasks:
- [x] Register rollback on init_tenant_db failure
- [x] Redis auth rate limit (fallback in-memory)
- [x] Enhanced /api/health + /metrics
- [x] Ops alert loop (Telegram)
- [x] Subscription lifecycle jobs (warn 7/1d, stop worker on expiry)
- [x] Admin API + UI expiring subscriptions
- [x] User index.html subscription expiry date
- [x] PRODUCTION-OPS D-4 alerts runbook
- [x] Worker monolith extraction — phase 1 (ADR 003)

---

## Epic: Billing / Payments

Status: BACKLOG — out of scope (manual subscriptions)

---

## Completed (historical)

- AI Agent System Bootstrap
- Multi-Tenant Worker Foundation (Phases 0–2)
- Phase 3 WS + Celery + Settings
- Campaign scale pacing (v18)
- Server review fixes, E2E, deploy verify

