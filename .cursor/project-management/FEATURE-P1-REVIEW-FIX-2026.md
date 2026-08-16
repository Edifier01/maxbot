# FEATURE PLAN — P1 review fixes 2026-08-16

**Status:** COMPLETE (2026-08-16) — verifier [PASS WITH NOTES](9e85f29c-be39-4884-bebe-5476525fcda0); parent pytest **64 passed** (P1 files); `docker compose config -q` OK  
**Zone:** `server`  
**Complexity:** MEDIUM  
**ADR required:** NO — enforces existing ADR 001 (tenant isolation) and ADR 002 (5s delay, proxy-per-group)

Source: project review 2026-08-16. User: proceed.

## In scope

1. Tenant-scoped campaign logs on `/api/status` and `/ws/status` (drop process-global `_log` leak in server mode)
2. Runtime delay floor 5s after lognormal (ADR 002); `delay_max_sec` API `ge=5`
3. Atomic volume restore: extract+verify, then swap; do not wipe live data first
4. Server-mode proxy fail-closed: no send without group proxy; ExtraConfig must not drop proxy and continue
5. Client IP for rate limits: rightmost `X-Forwarded-For` (one trusted hop / Caddy); fix inert IP `RateLimitMiddleware`
6. `POST /api/campaign/test`: refuse if worker busy; `advance_queue=False`

## Out of scope

- `main.py` split (ADR 003)
- `auto_run` subscription gate (P2)
- Non-root Docker USER (P2)
- Health-detail token check (P2)
- JWT omitted from JSON (P2)
- pytest skipif celery/psycopg DX (P2)
- `style-src 'unsafe-inline'`, PIN vault, lockfile CI (G-4)

## Domains affected

| Domain | Changes |
|--------|---------|
| Desktop | — |
| Server | `main.py`, `app/campaign_send.py`, `app/campaign_worker.py`, `app/routes_campaign.py`, `app/routes_models.py`, `app/middleware.py`, `app/auth_rate_limit.py`, `antiban_core.py`, `scripts/restore-volumes.sh` |
| Backend | status payload logs; IP rate limit count |
| Security | tenant log isolation; client IP for auth RL |
| Campaign | delay floor, proxy, test-send |
| DevOps | restore script |
| Testing | one test per behavior |

## Agent Assignment

| Agent | Task |
|-------|------|
| security-engineer | Client IP helper + AuthRateLimitMiddleware + RateLimitMiddleware count; tenant log payload isolation; tests |
| campaign-specialist | Delay floor, proxy fail-closed, campaign_test idle; tests |
| devops-engineer | restore-volumes.sh extract-verify-swap; update `test_backup_scripts.py` |
| backend-engineer | Wire status/WS logs to tenant `app_log` if security does not own that file; keep `append_log` SQLite insert |
| qa-engineer | After merge: pytest + compose-config |
| verifier | Evidence gate |

## Skills Assignment

| Skill | Why |
|-------|-----|
| maxserver-auth-security | Tenant log leak, X-Forwarded-For trust |
| maxserver-fastapi-backend | status, middleware, routes |
| maxserver-campaign | delay, proxy, test-send |
| antiban-campaign-safety | Do not weaken ADR 002 |
| maxserver-server-deploy | restore script |
| maxserver-testing | pytest evidence |

## Execution

- Round 1 (parallel): security, campaign, devops
- Round 2: parent integrate; backend only if log wiring leftover
- Round 3: qa + verifier

## Risks

| Risk | Mitigation |
|------|------------|
| Tenants without proxy cannot start | Intended in server mode; 400 with clear Russian message; admin sets proxy |
| XFF spoof if app port published | Rightmost hop; compose keeps app unpublished |
| Restore swap fails mid-move | Keep `.outgoing` until success; never wipe before extract |
| Delay floor changes desktop copy | This workspace is server-only |

## Verification

```
MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/ -q
docker compose config -q
```
