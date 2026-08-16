# Project Plan — MAX Sender Server

## Product Vision

Multi-tenant SaaS для controlled массовой рассылки в мессенджере MAX: учреждения регистрируются, получают подписку, управляют аккаунтами MAX, группами и кампаниями через веб-панель на VPS.

## Users And Roles

| Role | Доступ |
|------|--------|
| **User (tenant)** | Кабинет: группы, номера MAX, start/stop, stats (при активной подписке). Сообщения, настройки, pause, proxy — admin/impersonation (FEATURE-UX-OPS) |
| **Admin** | Пользователи, подписки, impersonation, глобальные настройки, stats |
| **Service (Celery)** | `INTERNAL_SERVICE_TOKEN` → campaign start/schedule |

## Core Domains

| Domain | Код / артефакты |
|--------|-----------------|
| Backend / API | `main.py`, `app/routes_*.py`, worker pool, MAX API |
| Frontend | `static/index.html`, `auth.html`, `admin.html` |
| Database (SaaS) | PostgreSQL: tenants, users, subscriptions, revoked_tokens |
| Database (tenant ops) | SQLite per tenant: profiles, groups, send_log |
| Security | JWT, vault, tenant isolation, rate limit, secrets |
| Campaign | antiban, warmup, pacing, pause/resume, worker |
| DevOps | Docker, Caddy, Redis, CI/CD, backup/restore |

## Milestones

### Milestone 1 — Foundation ✅

- FastAPI app + static UI
- Docker Compose (app, postgres, redis, caddy)
- Server mode (`MAX_SERVER_MODE=1`)
- JWT auth, register/login, admin bootstrap

### Milestone 2 — Core Product ✅

- Multi-tenant isolation (ContextVar + `data/tenants/{id}/`)
- Campaign engine (worker pool, anti-ban)
- Vault для сессий MAX
- Subscription gating
- WebSocket status, Prometheus metrics

### Milestone 3 — Admin / Operations ✅

- Admin panel (`admin.html`)
- Impersonation, subscription grant/revoke
- E2E tests (auth → admin → tenant isolation)
- Production runbook (`docs/PRODUCTION-OPS.md`)

### Milestone 4 — Integrations (partial)

- Celery profile (optional horizontal scale)
- Telegram notifications
- [ ] Billing / payments (out of scope — manual subscriptions)

### Milestone 5 — Production Readiness ✅

- [x] Register rollback on register
- [x] Redis auth rate limit (multi-replica)
- [x] Monitoring/alerting beyond health + metrics
- [x] Automated subscription lifecycle (manual billing)
- [x] User UI: subscription expiry date
- [x] Reduce `main.py` monolith (worker extraction phase 1–2 — ADR 003). Further split **PARTIAL** (~2845 lines remain; P3-3)
- ~~Core sync with desktop~~ — out of scope this epic

## Release Gates

Before production deploy:

1. CI green: `server-smoke`, `compose-config`, `server-e2e`
2. `.env` без placeholder secrets
3. `bash scripts/backup-volumes.sh`
4. `bash scripts/deploy.sh` + `verify_deploy.sh`
5. Verifier PASSED on changed domains

## Risks

| Risk | Mitigation |
|------|------------|
| Неофициальный MAX API | Anti-ban pacing, warmup, circuit breaker; campaign-specialist review |
| Monolith `main.py` ~2845 строк | Scoped changes; Feature Plan for further extract (ADR 003) |
| Hybrid PG + SQLite | Tenant paths documented; backup both volume + PG |
| Desktop/server code duplication | `check_core_sync.py`; mirror fixes when shared |
| Account bans | Campaign safeguards; no removal without approval |

## Out Of Scope

- Payment gateway / Stripe
- Mobile app
- Frontend build step (React/Vue)
- Kubernetes / serverless
- Desktop version (отдельный проект в monorepo)
