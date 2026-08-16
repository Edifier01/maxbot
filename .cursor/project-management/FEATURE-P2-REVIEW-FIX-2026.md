# FEATURE PLAN — P2 review residuals 2026-08-16

**Status:** COMPLETE (2026-08-16) — verifier [PASS WITH NOTES](5b0f7201-a7a5-42f5-a525-27c5494bb02f); parent pytest **191 passed, 26 skipped**  
**Zone:** `server`  
**Complexity:** MEDIUM  
**ADR required:** NO — closes ADR 008 residuals + review P2

Source: project review 2026-08-16. User: «Давай дальше» after P1 complete.

## In scope

1. `/api/health` extras only after **valid** cookie JWT or `INTERNAL_SERVICE_TOKEN` (junk `Authorization: x` stays thin public body). Docker HEALTHCHECK stays unauthenticated thin JSON (`ok`, `db_ok`, `server_mode`).
2. Server-mode login/register/restore/impersonate/exit JSON **omits** `token`. Cookie still set. Tests must use `Set-Cookie` / `response.cookies`, not `body["token"]`.
3. `/ws/status` server mode: cookie `max_token` only (ignore JSON `token`).
4. `change-me*` rejected at `before_start` for `JWT_SECRET`, `ADMIN_PASSWORD`, `INTERNAL_SERVICE_TOKEN` (server mode, not `MAX_TEST=1` if that would break CI — CI secrets are not `change-me*`).
5. `_try_auto_resume` / `scheduler_tick` skip tenants without `subscription_active`. Do **not** block admin HTTP start or service-token start.
6. Local pytest DX: skip celery tests if `celery` missing; skip PG modules if `DATABASE_URL` set but `psycopg` missing. CI with `requirements-server.txt` still runs them.

## Out of scope

- Non-root Docker USER
- `asyncio.to_thread` / main.py split
- Global TXT upload live-queue reset
- `worker_pool_size` delay scale
- `style-src 'unsafe-inline'`
- Health thin public fields (`db_ok`, `server_mode`) stay public on purpose

## Agent Assignment

| Agent | Task |
|-------|------|
| security-engineer | 1–4: health, omit JWT JSON, WS cookie-only, change-me gate + tests |
| campaign-specialist | 5: subscription gate on auto_resume/scheduler |
| backend-engineer | 6: conftest skip helper + celery/PG skipifs |
| qa-engineer | targeted + `tests/` counts |
| verifier | evidence |

## Skills Assignment

| Skill | Why |
|-------|-----|
| maxserver-auth-security | JWT cookie, health disclosure, change-me |
| maxserver-campaign | auto_run vs subscription |
| maxserver-fastapi-backend | health/auth/WS routes |
| maxserver-testing | skipif + pytest evidence |

## Verification

```
MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/ -q
```
Expect: P2 tests pass; without celery/psycopg, celery/PG modules **skip** (not error). Compose unchanged.
