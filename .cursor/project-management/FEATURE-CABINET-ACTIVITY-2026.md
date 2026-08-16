# FEATURE PLAN — Admin pacing UI, cabinet activity log, in-flight group lock

**Status:** COMPLETE (2026-08-16) — verifier [PASS WITH NOTES](0a8eaed0-248a-4e34-bda6-312127ca3641); targeted pytest **68 passed**; full suite **199 passed, 26 skipped** (15 fail = missing `email-validator` in this shell, not this diff)  
**Zone:** `server`  
**Complexity:** MEDIUM  
**ADR required:** NO — uses ADR 007 (global pacing copy) and ADR 001 (per-tenant workers)

Chat agreement (Ed, 2026-08-16):
1. **A** — полный антибан на вкладке админки; сохранение копирует во все учреждения.
2. Человеческий журнал в кабинете из `send_log`; техлог только админу/impersonation.
3. Воркеры: общая очередь + «группа занята — взять следующую»; без чёт/нечет.

## In scope

1. **Admin settings:** `/admin.html` вкладка «Настройки рассылки» показывает все ключи `GLOBAL_PACING_SETTING_KEYS` (окна, роли, паузы, presence, дедуп, circuit/cooldown). Save уже идёт в `PUT /api/settings` при `use_global_data()` → `propagate_global_pacing_settings`. Не тащить на эту вкладку: PIN, Telegram, webhook, backup, `worker_pool_size`, `auto_run` (остаются per-tenant / impersonation).
2. **Cabinet activity:** `/api/status` (+ WS) отдаёт `activity[]` — человеческие строки из последних send_log этого тенанта (без текста пула, без `#id` воркера). Кабинет рисует журнал под сводкой. Техполе `log` в UI кабинета не показываем (как сейчас).
3. **In-flight groups:** per-tenant set на `CampaignRuntime`; `claim_next_job` не выдаёт группу, которую другой воркер этого тенанта сейчас шлёт. Pool=1 без изменения поведения.

## Out of scope

- Sticky even/odd group assignment
- New activity table / migration
- Desktop copy
- Billing, PIN vault, `style-src`, main.py split

## Agent Assignment

| Agent | Task |
|-------|------|
| campaign-specialist | In-flight group lock in claim/send; tests (2 workers ≠ same group; pool=1 unchanged) |
| backend-engineer | `activity` on status payload; humanize send_log; tests; no pool text |
| frontend-engineer | admin.html full pacing form + admin.js load/save; cabinet activity panel |
| security-engineer | After code: tenant isolation of activity; cabinet vs admin log; no TXT leak |
| qa-engineer | pytest + static contracts |
| verifier | Evidence gate |

## Skills Assignment

| Skill | Why |
|-------|-----|
| maxserver-campaign | worker claim, antiban, proxy-per-group |
| antiban-campaign-safety | do not weaken pacing; avoid same-group dual send |
| maxserver-fastapi-backend | status payload |
| maxserver-auth-security | tenant-scoped activity |
| maxserver-static-ui | admin + cabinet vanilla UI |
| maxserver-testing | pytest + `test_saas_ux_static.py` |

## Execution

- Round 1 (parallel): campaign + backend + frontend
- Round 2: security-engineer review
- Round 3: qa + verifier

## Risks

- Admin form miss a pacing key → tenants keep DEFAULTS for that key. Mitigate: static test that admin save body includes every `GLOBAL_PACING_SETTING_KEYS` id.
- Two workers + 1 group: second waits (None + sleep). Intended.
- Activity XSS: escape in existing `esc()`.

## Verification

- `MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/ -q` (targeted files OK if full suite env-limited)
- `tests/test_saas_ux_static.py` — admin pacing fields + cabinet activity DOM
- Manual: admin save copies windows to tenant; cabinet sees «отправлено в …»; 2 workers don't claim same group_id concurrently
