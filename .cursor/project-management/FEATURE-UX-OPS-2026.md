# Feature Plan — UX + ops hardening (2026-08-13)

**Status:** COMPLETE (2026-08-13) — parent pytest **131 passed, 19 skipped**; verifier PASS WITH NOTES  
**Zone:** `server`  
**Complexity:** HIGH  
**ADR required:** YES — 007 global pacing settings vs tenant workers; pause vs auto_run

## Feature
Закрыть дыры аудита (пауза, настройки админки, подписка, UI) **без расширения** кабинета учреждения.

## Locked product constraint (Ed, 2026-08-13)

Учреждение (`role=user`) **только**:
- создавать / удалять группы
- добавлять номера и входить в MAX (уже есть, не убирать)
- Старт / Стоп
- видеть статистику (сводка `dashStats`)

**Не добавлять** пользователю: пауза, прокси, CSV, сообщения, настройки, `is_active`, превью пула, смену пароля, прогресс-бар.

**Удалить** из кабинета учреждения: блок прогресса (`#dashProgressPanel`, шапка `#progressWrap`).

Админ / impersonation — полный ops-набор (пауза, тест, пул, настройки, прокси, CSV, `is_active`).

## Domains affected
- Desktop: no
- Server: yes
- Backend: campaign pause/auto_run, settings propagate, groups `is_active`, phone lookup, message_idx, subscription
- Frontend: `static/index.html`, `admin.html`, `auth.html`
- Database: subscription extend/revoke/`expires_at` when inactive (PG helpers; schema likely unchanged)
- Security: tenant isolation on settings copy; subscription revoke; impersonation start gate
- DevOps: no
- Testing: pytest + static contracts

## Agent Assignment
- campaign-specialist → pause/auto_run/schedule/retry
- security-engineer → settings scope propagate + ADR 007 + revoke authz
- database-engineer → subscription extend/revoke/expired timestamp
- backend-engineer → `is_active` PATCH, phone lookup, message_idx reset
- frontend-engineer → UI per brief + tenant constraint
- qa-engineer → tests evidence (after integration)
- verifier → gate (after QA)

## Skills Assignment
- `antiban-campaign-safety` → pause/auto_run
- `tenant-isolation-max` + `security-review` + `saas-multi-tenant` → settings copy
- `postgres-patterns` + `database-migrations` → subscriptions
- `fastapi-patterns` → groups/messages APIs
- `maxserver-static-ui` + `frontend-design-max` → panels
- `python-testing` → pytest

## Execution
- Round 1 (parallel): campaign, security, database, backend, frontend
- Round 2: parent integrate
- Round 3: qa-engineer → verifier

## Risks
- Copying settings to all tenants: allowlist only; never `api_pin` / telegram tokens / `auto_run` / `worker_pool_size`
- Pause must not weaken anti-ban; only stop auto-resume
- Tenant UI must not gain new controls

## Verification
```
MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/ -q
```
Manual: user cabinet = groups + start/stop + stats, no progress; admin pause holds; admin settings change tenant send delays; TXT upload shows filename + count; login Enter.
