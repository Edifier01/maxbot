# Tasks

## Backlog
- Decide later whether to extract shared code into a package; do not do this without a Feature Plan.
- Optional: вынос worker loops из `main.py` в `campaign_worker.py`.

## Done
- Split project into `desktop/` and `server/`.
- Added a common AI agent system for both versions.
- Server review fixes P0–P3 (см. `SERVER-REVIEW-FIX-PLAN.md`).
- Server unit/smoke tests: auth, tenant isolation, rate limit, JWT revoke, migrations (`server/tests/`, CI job `server-smoke`).
- Core sync checklist + `scripts/check_core_sync.py` (см. `docs/CORE-SYNC.md`).
- Production ops: `verify_deploy.sh`, `backup-volumes.sh`, `restore-volumes.sh`, runbook `server/docs/PRODUCTION-OPS.md`, CI `compose-config`, Celery smoke tests.
- E2E smoke: auth → admin → subscription → tenant isolation (`server/tests/test_e2e_server.py`, CI job `server-e2e` + PostgreSQL).
