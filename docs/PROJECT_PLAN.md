# Project Plan — MAX Sender Server

> Исторический план продукта. Отметки milestones и оценки размера файлов
> относятся к прежнему состоянию проекта. Текущий код и команды описаны в
> `README.md`, `docs/HOW-IT-WORKS.md` и `.github/workflows/ci.yml`; текущее
> решение о выпуске — в `docs/audit/release-gate.md`.

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

- Celery profile (optional trigger worker; one app replica)
- Telegram notifications
- [ ] Billing / payments (out of scope — manual subscriptions)

### Milestone 5 — Local production-readiness candidate (`FIX / PARTIAL`)

- [x] Register rollback on register
- [x] Redis auth rate limit (multi-replica)
- [x] Monitoring/alerting beyond health + metrics
- [x] Automated subscription lifecycle (manual billing)
- [x] User UI: subscription expiry date
- [x] Reduce `main.py` monolith (worker extraction phase 1–2 — ADR 003). Further split **PARTIAL** (~2845 lines remain; P3-3)
- ~~Core sync with desktop~~ — out of scope this epic

The local source candidate has focused safety, integration, static and browser
evidence, but this milestone is not a production `GO`: normative Master
acceptance, independent platform authorization, image CVE review,
secret-history ownership and VPS/live verification remain open. See
`docs/audit/final-review.md` and `docs/audit/release-gate.md` for the
commit-bound handoff.

## Release Gates

Before production deploy:

1. CI green: `server-smoke`, `compose-config`, `server-e2e` — must be rerun for the final SHA
2. `.env` без placeholder secrets — operator-only, not present in Git
3. `bash scripts/backup-volumes.sh` — operator-only before deploy
4. `bash scripts/deploy.sh` + `verify_deploy.sh` — production gate, not run locally here
5. Verifier PASSED on changed domains — focused local evidence exists; Master/production evidence remains open

## Risks

| Risk | Mitigation |
|------|------------|
| Неофициальный MAX API | Anti-ban pacing, warmup, circuit breaker; campaign-specialist review |
| Monolith `main.py` ~2845 строк | Scoped changes; Feature Plan for further extract (ADR 003) |
| Hybrid PG + SQLite | Tenant paths documented; backup both volume + PG |
| Один runtime с локальным и server mode | Проверять обе конфигурации и tenant scope в одном дереве |
| Account bans | Campaign safeguards; no removal without approval |

## Out Of Scope

- Payment gateway / Stripe
- Mobile app
- Frontend build step (React/Vue)
- Kubernetes / serverless
- Отдельное desktop-приложение (в этом репозитории его нет)
