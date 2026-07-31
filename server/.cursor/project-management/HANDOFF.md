# Handoff

## Completed (2026-07-31) — Admin impersonation: campaign UI + /me email

- **index.html:** режим `isAdminImpersonating()` / `isSimpleCampaignView()` — в кабинете tenant у админа только Старт/Стоп; скрыты пауза, сброс, тест, расписание, **живой лог**, **история кампаний**, **история отправок**; подсветка активной кнопки как у user
- **routes_auth.py:** `/auth/me` при impersonation — `email` = пользователь tenant, `actor_email` = админ
- **tests/test_admin_impersonation_campaign.py** — me email, status/log, campaigns, send_log, stop/start API (e2e, skip без PG)

### Validation
```
pytest → 78 passed, 5 skipped
```

## Completed (2026-07-31) — Mobile UI + Admin bulk groups

- **Mobile:** responsive CSS `@media (max-width: 720px)` для `index.html`, `auth.html`, `admin.html`
- **Admin API:** `POST /api/admin/groups/activate-all`, `POST /api/admin/groups/deactivate-all` — `groups.is_active` для всех tenant
- **admin.html:** панель «Группы всех учреждений» + confirm + статус
- `tests/test_admin_groups_bulk.py`

### Validation
```
pytest tests/test_admin_groups_bulk.py → 2 passed
```

## Completed (2026-07-31) — Role rotation 33/33/33 (ordered, 3-day cycle)

- Роли дня: **детерминированная ротация** вместо `random.shuffle` + процентов
- Группа делится на 3 части (~33%); остаток `n%3` — **первым частям** (10 → 4+3+3)
- Цикл: active → quiet → skip; части со сдвигом (+0/+1/+2), в один день роли не пересекаются
- Якорь `role_cycle_anchor` в settings при **первом** `/api/campaign/start`; **без сброса** при перезапуске
- `antiban_core.py`: `split_thirds`, `role_rotation_for_part`, `assign_rotation_roles`
- `app/campaign_query.py`: `_ensure_group_role_plan` переписан
- `main.py`: `_ensure_role_cycle_anchor`, `_role_cycle_day`, fallback `MIN(campaigns.started_at)`
- `tests/test_role_rotation.py` — 6 тестов

### Validation
```
pytest tests/test_role_rotation.py tests/test_role_plan_percent.py → 11 passed
```

## Completed (2026-07-31) — P3-3 Main.py monolith split (ADR 003 ph3)

- `app/sqlite_backend.py` — `_conn`, `init_db`, `_migrate_*`, connection pool globals
- `app/campaign_queue.py` — message bag, `_pick_next_message`
- `app/campaign_query.py` — `_active_groups`, `_active_profiles_for_group`, `_ensure_group_role_plan`
- `main.py` — re-exports; ~650 LOC removed (3200 → ~2550)
- `tools/patch_main_p33.py` — one-shot extraction script

### Validation
```
pytest → 64 passed, 4 skipped
```

## Completed (2026-07-31) — P2-5 Main import consolidation

- `app/runtime.py` — single `_MainProxy` lazy bridge to root `main.py`
- `app/campaign_facade.py` — thin re-export for backward compat
- Migrated 17 modules: all `routes_*`, middleware, hooks, tenant_sqlite, ops_monitor, subscription_jobs, campaign_worker
- Removed ~60 inline `import main as m` from handlers
- `routes_auth.py`: `import os` moved to module top

### Validation
```
pytest → 64 passed, 4 skipped
rg 'import main as' app/routes_*.py app/middleware.py → 0 inline (only from app.runtime)
```

## Completed (2026-07-31) — Code Review Fixes

### Wave 1 (P0)
- `middleware.py` — extract role/tenant_id/impersonating from JWT payload
- `ops_monitor.py` — fix `circuit_threshold` NameError in `_tick`
- `auth_rate_limit.py` — `global` in Redis exception handler

### Wave 2 (P1)
- `db_pg.py` — double-checked locking for pool init
- `tenant_init.py` — `tenant_scope` for context restore on error
- `static/index.html` + `PRODUCTION-OPS.md` — vault legacy/protected warning
- `campaign_worker.py` — `scheduler_tenant_ids()` from PG
- `docker-compose.yml` — POSTGRES_PASSWORD required (no default)

### Wave 3 (P2/P3/M)
- `requirements-scale.txt` → `requirements-server.txt` (+ Dockerfile, CI, README)
- `db_pg.py` — pool timeout/max_waiting, single `_now()`, bootstrap transaction
- `campaign_worker.py` — `notify_campaign_end` via `telegram_notify`
- `routes_auth.py` — `/me` relies on middleware context only
- `vault.py` — `unlink(missing_ok=True)`
- `subscription_jobs.py` — comment on `_stopped_expired`
- `celery_worker.py` — explicit REDIS_URL required
- `docker-compose.yml` — migrations only via Python runner (bootstrap in initdb.d)
- Refactor scripts → `tools/refactor-scripts/`, `schema_pg_legacy.sql` → `docs/archive/`
- `.dockerignore` added

### Excluded (separate feature)
- P3-3: main.py monolith split

### Validation
```
pytest → 64 passed, 4 skipped
```

## Prior (2026-07-31) — Worker Monolith Phase 2
- campaign_send, campaign_facade, ADR 003 phase 2

## Backlog
- P2-5 / P3-3 main.py refactor (separate `/start-feature`)
- Full PIN-vault for new tenants (beyond UI warning)

## Prior rounds
- Agent Review R1–3 + security tail
- Worker phase 1 (ADR 003)
