# Tasks

## In progress
_(none)_

## Backlog
- Decide later whether to extract shared code into a package; do not do this without a Feature Plan.
- Optional: further `main.py` worker/core extraction (ADR 003 — deferred).
- Optional: `asyncio.to_thread` for SQLite in non-admin routes (M-5 started with `routes_admin` only).
- Optional: CI install from `*.lock` (today lockfiles are Docker-only; CI uses `requirements*.txt`).

## Done
- **UI polish / web-design-guidelines (2026-08-16):** installed official Vercel skill into `.agents/skills/` + harness copy `.cursor/skills/web-design-guidelines`; unified static panels (auth/admin → tenant chrome). `test_saas_ux_static.py` **14 passed**. Verifier PASS WITH NOTES.
- **FEATURE-CABINET-ACTIVITY-2026** (2026-08-16): full admin pacing UI (all `GLOBAL_PACING_SETTING_KEYS`); cabinet human `activity` journal; per-tenant in-flight group lock (no even/odd). Verifier [PASS WITH NOTES](0a8eaed0-248a-4e34-bda6-312127ca3641). Targeted pytest **68 passed**.
- **FEATURE-P3-REVIEW-FIX-2026** (2026-08-16): delete unused `campaign_store`; flood-wait sleep N; per-tenant `claim_lock`; backup archive verify; compose sidecar digest pins; mocked MAX login + `send_with_retry` success. Verifier [PASS WITH NOTES](ceb43ba6-7e23-4fc7-b5d1-4270fb71cb39). Pytest **197 passed, 26 skipped**. Compose config OK.
- **FEATURE-P2-REVIEW-FIX-2026** (2026-08-16): health extras gated; omit JSON JWT; WS cookie-only; change-me startup; auto_run subscription skip; skipif psycopg_pool/celery. Verifier [PASS WITH NOTES](5b0f7201-a7a5-42f5-a525-27c5494bb02f). Pytest **191 passed, 26 skipped**.
- **FEATURE-P1-REVIEW-FIX-2026** (2026-08-16): tenant status/WS logs; runtime delay floor 5s; atomic restore; proxy fail-closed; rightmost XFF + IP RL count; campaign/test 409 + no rewind. Verifier [PASS WITH NOTES](9e85f29c-be39-4884-bebe-5476525fcda0). Pytest **64 passed** (targeted). Compose config OK.
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
