# Tasks

## Backlog
- Decide later whether to extract shared code into a package; do not do this without a Feature Plan.
- Optional: further `main.py` worker/core extraction (ADR 003 — deferred).
- Optional: `asyncio.to_thread` for SQLite in non-admin routes (M-5 started with `routes_admin` only).
- Optional: CI install from `*.lock` (today lockfiles are Docker-only; CI uses `requirements*.txt`).

## Done
- Split project into `desktop/` and `server/`.
- Added a common AI agent system for both versions.
- Server review fixes P0–P3 (см. `SERVER-REVIEW-FIX-PLAN.md`).
- Agent Fix Plan 2026 C-1…L-3 (см. `AGENT-FIX-PLAN-2026.md`): asyncio claim lock, Redis healthcheck, delete_tenant order, session cache, CSP verify, proxy validation, mutation rate limit, stdout logs, remove `tools/`, migration lock hash, admin `to_thread`, requirements lock + Docker digest, timezone in `.env.example`.
- G-2: tenant group proxy PATCH/CREATE allowed in server mode (UI `saveGroupProxy` works).
- Server unit/smoke tests: auth, tenant isolation, rate limit, JWT revoke, migrations (`server/tests/`, CI job `server-smoke`).
- Core sync checklist + `scripts/check_core_sync.py` (см. `docs/CORE-SYNC.md`).
- Production ops: `verify_deploy.sh`, `backup-volumes.sh`, `restore-volumes.sh`, runbook `server/docs/PRODUCTION-OPS.md`, CI `compose-config`, Celery smoke tests.
- E2E smoke: auth → admin → subscription → tenant isolation (`server/tests/test_e2e_server.py`, CI job `server-e2e` + PostgreSQL).
