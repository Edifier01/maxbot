# Feature Plan — Review P1 fixes (2026-08-13)

**Status:** COMPLETE (2026-08-13) — verifier PASS WITH NOTES; parent pytest **148 passed, 19 skipped**; `docker compose config -q` → `REGISTRATION_OPEN=0`  
**Zone:** `server`  
**Complexity:** HIGH  
**ADR required:** NO — AuthZ/ops hardening, no architecture change

## Feature

Закрыть P1 из полного ревью 2026-08-13 **без** cookie-only CSP, без split `main.py`, без ослабления pacing.

### In scope (волна 1)

1. **AuthZ cabinet lock** — `role=user` только: groups CRUD (без proxy/`is_active`), phones/login, start/stop, stats. 403 на pause/reset/test/schedule/retry_failed, GET messages/settings, bulk CSV, proxy/`is_active` PATCH.
2. **Impersonation** — `/api/admin` и `_require_admin()` отклоняют `imp=true`. Impersonation JWT остаётся для tenant ops на `index.html`.
3. **Subscription** — `POST /api/campaign/retry_failed` (и `test`) как start: 403 без активной подписки.
4. **Compose** — прокинуть `REGISTRATION_OPEN` (дефолт `0` как `.env.example`), `AUTH_RATE_LIMIT`, `AUTH_RATE_WINDOW_SEC`.
5. **Campaign** — alias `_reset_queue_progress`; `stop_worker` не `await` сам себя; watchdog не стартует если `auto_run=0`.
6. **DR** — backup перед rebuild если стек уже жив; `pg_restore` без `|| true`.

### Out of scope

- Cookie-only JWT / CSP без `unsafe-inline`
- 410 vault setup/unlock
- CI Postgres для 15 skipif
- `delay_min_sec` floor 5
- Celery как отдельный send engine
- ADR 003 extraction

## Domains affected

- Desktop: no
- Server: yes
- Backend: middleware, routes_admin, routes_groups, routes_campaign (gates only)
- Frontend: no (UI already hides)
- Database: no schema
- Security: AuthZ + impersonation
- DevOps: compose env, deploy/restore scripts
- Campaign: stop_worker, watchdog, reset alias
- Testing: pytest AuthZ + campaign + compose config

## Agent Assignment

- security-engineer → AuthZ middleware, `_require_admin` + imp, groups field gates, subscription on retry/test, tests
- campaign-antiban → `stop_worker` / watchdog / `_reset_queue_progress` re-export; **не** менять delays
- devops-engineer → Compose env inject; deploy backup; restore fail-closed
- qa-engineer → после интеграции
- verifier → после QA

## Skills Assignment

- `security-review` + `tenant-isolation-max` → AuthZ
- `antiban-campaign-safety` → worker stop (не трогать pacing)
- `docker-patterns` + `backup-hybrid-storage` + `deployment-patterns` → compose/DR
- `python-testing` → pytest
- `fastapi-patterns` → middleware/routes

## Execution

- Round 1 (parallel): security-engineer, campaign-antiban, devops-engineer
- Round 2: parent merge
- Round 3: qa-engineer → verifier

## Risks

- Impersonation admin UI uses `maxAdminAuthToken` — `/api/admin` с imp-токеном должен 403; кабинет с imp остаётся полным ops (role=admin)
- User start/stop must stay 200 (подписка только на start/schedule/retry/test)
- First deploy: backup skip if postgres not up
- `stop_worker` from send loop must still set `auto_run=0` and finish campaign

## Verification

```
MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/ -q
```

Compose: `docker compose config -q` with required env including `REGISTRATION_OPEN=0`.
