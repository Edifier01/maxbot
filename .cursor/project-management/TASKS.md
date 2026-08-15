# Tasks

## In progress
_(none)_

## Backlog
- Decide later whether to extract shared code into a package; do not do this without a Feature Plan.
- Optional: further `main.py` worker/core extraction (ADR 003 — deferred).
- Optional: `asyncio.to_thread` for SQLite in non-admin routes (M-5 started with `routes_admin` only).
- Optional: CI install from `*.lock` (today lockfiles are Docker-only; CI uses `requirements*.txt`).

## Done
- **FEATURE-RESIDUALS-2026** (2026-08-15): REGISTRATION_OPEN fail-closed 0; CI 15 skipif isolated; cookie-only JWT (ADR 008) + CSP `script-src 'self'`; UI toast/progressWrap/skip-link; Celery empty-token fail-closed. Verifier [PASS WITH NOTES](f200e084-1724-4e7a-bc06-566254c425f0). Pytest **181 passed, 19 skipped**.
- **Plan vs Reality Review 2026-08-15:** verifier PASS WITH NOTES. Pytest **165 passed, 19 skipped**. Audits refreshed. In-scope residuals closed by FEATURE-RESIDUALS-2026.
- **Harness DX 2026-08-15:** `maxserver-*` facades on disk + `/ponytail-review` + `/audit-harness` + NameThatUI in UI workflow. No product runtime change.
- **Hotfix MAX client version** (2026-08-14): `maxapi-python==2.4.0` + pin preferred app_version; pytest 163 passed, 19 skipped.
- **FEATURE-REVIEW-FIX-2026 wave 2** (2026-08-13): profile proxy cabinet 403, vault password APIs 410 in server mode, delay_min_sec ≥ 5. Verifier [PASS WITH NOTES](990a477f-5db3-45f2-a238-8741b73e58ab). Pytest 155 passed, 19 skipped.
- **FEATURE-REVIEW-FIX-2026 wave 1** (2026-08-13): AuthZ cabinet lock + impersonation `/api/admin` 403 + Compose `REGISTRATION_OPEN=0` + `stop_worker`/watchdog/`reset` + deploy backup/restore fail-closed. Verifier [PASS WITH NOTES](5a1474e2-4f02-48c1-8bb0-44e49c1ad2d2). Pytest 148 passed, 19 skipped.
- **FEATURE-UX-OPS-2026** (2026-08-13): pause vs auto_run, admin pacing → tenants (ADR 007), subscription extend/revoke, groups `is_active` + phone lookup, admin/auth UI; tenant cabinet stays groups/start-stop/stats, progress removed. Verifier PASS WITH NOTES; pytest 131 passed, 19 skipped.
- **FEATURE-VAULT-CI-2026** (2026-08-09): vault hot-path isolation + CI Postgres on smoke; ADR-006; HOW-IT-WORKS `.app_key` threat model. Verifier + security PASS WITH NOTES; parent pytest 110 passed, 13 skipped.
- **FEATURE-MOBILE-2026** (2026-08-08): mobile polish `@media 720px` on tenant/admin/auth static panels (touch 44px, safe-area, admin form/table/toast parity). Verifier PASS WITH NOTES; pytest 108 passed, 13 skipped. P2 badge chrome deferred.
- **FEATURE-SAAS-UX-2026** (2026-08-07): subscription UX, `banned` status, ban→stop-all, summary on campaign tab, admin global settings/messages, per-user `worker_pool_size`, delete user hardening. ADR 004/005. Tests: 100 passed + `test_saas_ux_static.py`. Verifier: [PASS](d8a3d3bc-87f9-4d19-b73b-044bf82b4239).
- Split project into `desktop/` and `server/`.
- Added a common AI agent system for both versions.
- Server review fixes P0–P3 (см. `SERVER-REVIEW-FIX-PLAN.md`).
- Agent Fix Plan 2026 C-1…L-3 (см. `AGENT-FIX-PLAN-2026.md`): asyncio claim lock, Redis healthcheck, delete_tenant order, session cache, CSP verify, proxy validation, mutation rate limit, stdout logs, remove `tools/`, migration lock hash, admin `to_thread`, requirements lock + Docker digest, timezone in `.env.example`.
- G-2 group proxy for tenants superseded by REVIEW-FIX-2026 (user 403; admin/imp still can).
- Server unit/smoke tests: auth, tenant isolation, rate limit, JWT revoke, migrations (`server/tests/`, CI job `server-smoke`).
- Core sync checklist + `scripts/check_core_sync.py` (см. `docs/CORE-SYNC.md`).
- Production ops: `verify_deploy.sh`, `backup-volumes.sh`, `restore-volumes.sh`, runbook `server/docs/PRODUCTION-OPS.md`, CI `compose-config`, Celery smoke tests.
- E2E smoke: auth → admin → subscription → tenant isolation (`server/tests/test_e2e_server.py`, CI job `server-e2e` + PostgreSQL).
