# SERVER REVIEW FIX PLAN

Источник: ревью серверной части MAX Sender (чат 2026-07-29).

## FEATURE PLAN

**Feature:** Исправления по результатам server review (P0 → P3)  
**Complexity:** MEDIUM  
**ADR required:** NO — точечные исправления без смены архитектуры  
**Zone:** `server`

### Domains affected

| Домен | Изменения |
|-------|-----------|
| Desktop | — |
| Server | `db_pg.py`, `main.py`, `middleware.py`, `routes_admin.py`, `tenant_init.py` |
| Backend | Connection pool PG, tenant-safe paths |
| Frontend | — |
| Database | Pool + транзакции (P1) |
| Security | Rate limit auth (P1) |
| DevOps | HEALTHCHECK app (P2) |
| Testing | Smoke для pool + tenant paths |

### Agent Assignment

| Agent | Задача |
|-------|--------|
| backend-engineer | P0 paths + middleware, P1 auth rate limit |
| database-engineer | P0 pool, P1 register_user transaction, P2 migrations |
| security-engineer | P1 rate limit, review JWT ephemeral dev |
| devops-engineer | P2 Dockerfile HEALTHCHECK, compose health |
| qa-engineer | Verification после каждой волны |

### Skills Assignment

| Skill | Зачем |
|-------|-------|
| maxserver-postgresql | Pool, schema, transactions |
| maxserver-fastapi-backend | Middleware, routes |
| maxserver-auth-security | Rate limit, JWT |
| maxserver-server-deploy | HEALTHCHECK, compose |
| maxserver-testing | Smoke/regression |

---

## Backlog по приоритетам

### P0 — критично (текущий спринт)

| # | Проблема | Решение | Статус |
|---|----------|---------|--------|
| P0-1 | `db_pg.py`: один global conn, нет reconnect | `psycopg_pool.ConnectionPool`, checkout на запрос | DONE |
| P0-2 | Race: `_refresh_data_paths()` мутирует globals в middleware | Path-хелперы через `_resolve_data_dir()`; убрать per-request refresh/reset | DONE |

### P1 — высокий

| # | Проблема | Решение | Статус |
|---|----------|---------|--------|
| P1-1 | `register_user`: orphan tenant при сбое между INSERT | Транзакция `register_tenant_user` | DONE |
| P1-2 | Нет rate limit на `/api/auth/*` | `AuthRateLimitMiddleware` (10/15min default) | DONE |
| P1-3 | `assert row` в production-пути | Явный `raise` в db_pg + routes_auth | DONE |
| P1-4 | `_fernet` / `_vault_unlocked` глобальны между tenant | `_vault_by_data` keyed by data-dir | DONE |

### P2 — средний

| # | Проблема | Решение | Статус |
|---|----------|---------|--------|
| P2-1 | Нет миграций схемы PG | `schema_migrations` + `migrations/*.sql` + README | DONE |
| P2-2 | Нет HEALTHCHECK для `app` в compose | Dockerfile + compose; Caddy `service_healthy` | DONE |
| P2-3 | Legacy-таблицы в `schema_pg.sql` не используются | `schema_pg_legacy.sql` | DONE |
| P2-4 | Celery без JWT к campaign API | `INTERNAL_SERVICE_TOKEN` | DONE |

### P3 — низкий

| # | Проблема | Решение | Статус |
|---|----------|---------|--------|
| P3-1 | `set_context` в admin handlers без restore | `tenant_scope` + `tenant_conn` | DONE |
| P3-2 | JWT blacklist / revoke | `jti` + `revoked_tokens` + `/api/auth/logout` | DONE |
| P3-3 | Декомпозиция `main.py` | `paths.py`, `vault_store.py`, `tenant_sqlite.py` | PARTIAL |

---

## Execution

### Round 1 (P0) — текущий

1. `db_pg.py` → ConnectionPool
2. `main.py` → `_data_dir()`, `_db_path()`, `_sessions_root()` и замена hot-path
3. `middleware.py` → убрать `_refresh_data_paths` / `_reset_db_conn` per request
4. `routes_admin.py`, `tenant_init.py` → убрать лишний refresh
5. Минимальный self-check / smoke

### Round 2 (P1) — DONE

1. Transaction в `register_tenant_user`
2. Rate limit auth endpoints
3. Замена `assert` на explicit errors
4. Per-tenant vault cache

### Round 3 (P2) — DONE

1. HEALTHCHECK + compose + fix Dockerfile COPY paths
2. Migration runner + split schema
3. Celery `INTERNAL_SERVICE_TOKEN`
4. Fix `/api/health` → `db_pg.ping()`

### Round 4 (P3) — DONE (P3-3 partial)

1. `tenant_scope` / `tenant_sqlite.tenant_conn`
2. JWT `jti` + `002_revoked_tokens` + logout
3. Admin routes на `tenant_conn`

### Backlog (post-review)

- Worker loops + core logic остаются в `main.py` (~4300 строк)
- ~~Bulk revoke JWT при delete tenant~~ → middleware: user/tenant must exist in PG
- Вынесено: `vault.py`, `campaign_*`, все `routes_*`, `routes_models.py`

---

## Risks

| Риск | Митигация |
|------|-----------|
| Регресс desktop/local mode | Smoke `desktop/tests/` без `MAX_SERVER_MODE` |
| Pool exhaustion | max_size=10, мониторинг `/api/health` |
| Пропущенные globals в main.py | Grep `SESSIONS\|DB_PATH\|MESSAGES_FILE` после P0 |

## Verification

```bash
cd maxserverapp/desktop && python -m pytest tests/test_smoke_health.py -q
cd maxserverapp/server && python -m pytest tests/ -q   # после добавления
cd maxserverapp/server && docker compose config
```

Manual (server mode): два tenant, параллельные GET `/api/status` — разные `tenant_id` в данных.
