# Tasks

## Epic: Worker Monolith Refactor

Status: COMPLETED (phase 1)  
Owner: backend-engineer  
Scope: mechanical extraction → `app/campaign_worker.py`, lazy main bridge

Tasks:
- [x] Update extract/patch scripts with current line ranges
- [x] Generate `app/campaign_worker.py` (~780 lines)
- [x] Patch `main.py` imports (re-export `_start_worker`, etc.)
- [x] Fix `test_worker_tenant_runtime` patch target
- [x] ADR 003 → Accepted (phase 1)
- [ ] Phase 2: decouple lazy `_m()` bridge, move send/pacing (future `/start-feature`)

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
