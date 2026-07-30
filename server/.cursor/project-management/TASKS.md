# Tasks

## Epic: Milestone 5 — Production Readiness

Status: COMPLETED  
Owner: backend + frontend + devops  
Scope: monitoring, subscription lifecycle, register rollback, Redis auth RL

Tasks:
- [x] Register rollback on init_tenant_db failure
- [x] Redis auth rate limit (fallback in-memory)
- [x] Enhanced /api/health + /metrics
- [x] Ops alert loop (Telegram)
- [x] Subscription lifecycle jobs (warn 7/1d, stop worker on expiry)
- [x] Admin API + UI expiring subscriptions
- [x] User index.html subscription expiry date
- [x] PRODUCTION-OPS D-4 alerts runbook
- [ ] Worker monolith extraction — **deferred** (ADR 003)

Validation:
- [x] pytest 44 passed, 4 skipped
- [x] ADR 003 deferred worker extraction

---

## Epic: Worker Monolith Refactor

Status: BACKLOG (deferred per ADR 003)  
Depends on: committed main.py baseline + `/start-feature`

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
