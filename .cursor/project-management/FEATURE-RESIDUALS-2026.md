# Feature Plan — Residuals Plan vs Reality Review 2026-08-15

**Status:** COMPLETE (2026-08-15) — verifier [PASS WITH NOTES](f200e084-1724-4e7a-bc06-566254c425f0); parent pytest **181 passed, 19 skipped**; `docker compose config -q` OK  
**Zone:** `server`  
**Complexity:** HIGH  
**ADR:** 008 cookie-only JWT (Accepted)

Source: `knowledge-catalog/reports/max-sender-gap.md` Residuals + HANDOFF 2026-08-15.

## In scope (done)

1. `REGISTRATION_OPEN` Python fallback `"0"` (fail-closed)
2. CI `server-smoke`: 15 `DATABASE_URL` skipifs in a **separate** pytest process
3. Cookie-only JWT + CSP `script-src 'self'` (no script `'unsafe-inline'`)
4. UI: subscription start toast; remove hidden `#progressWrap`; skip-link on admin/auth (no custom modal to trap)
5. Celery: empty `INTERNAL_SERVICE_TOKEN` raises; no Authorization; no unauthenticated start

## Out of scope (unchanged)

- `main.py` split (ADR 003 / P3-3)
- `to_thread` beyond admin/claim
- mobile P2 badge chrome
- extra-agent wiring
- `style-src` without `'unsafe-inline'`

## Agents

Round 1: security [c11fc457](c11fc457-955d-4dd8-a3a9-3050eee29c74), campaign [6baa1648](6baa1648-5cab-458d-a26b-6b56428726ba), devops [67cadf32](67cadf32-b076-477c-bd40-6fab9fcc6187), frontend [a587b936](a587b936-be5e-497d-8410-7d85c4eeb166)  
Round 2: frontend [5f8aff05](5f8aff05-72f2-450a-a310-b59f8ed6d211), devops [7892d68e](7892d68e-57d5-48d3-9c9f-b8c2adf47185), security [08b33072](08b33072-4d1d-4521-a439-5c7612bdd896)  
Round 3: qa [5893416f](5893416f-800e-447c-be9e-583e3234d443), verifier [f200e084](f200e084-1724-4e7a-bc06-566254c425f0)

## Verification

```
MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/ -q
→ 181 passed, 19 skipped
docker compose config -q → OK
```
