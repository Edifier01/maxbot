# MAXBOT verification matrix

Schema for each evidence row:

`case_id | candidate_sha | command | environment | started_at | exit_code | result | evidence_ref | limitation`

The candidate is the dirty working tree at `0154884cf94d6aeccf65f5390a0f845d783c3c0e`; rows are not commit-bound.

## Task graph linkage

`ENV-00 -> S00`; `S00 -> T00/T01`; `T01/T02 -> S01`; `S01 -> S02 ->
S02A`; `S02A -> T03/T06/T12`; `S02 -> T11/T13`; `S03 -> T10/T14/T28`;
`T15 -> T33 -> T14`; `S04 -> T29/T30`; `S05 -> T32`.

The original Master `T00..T33`, `AUD20-A01..A46`, and `COMP-R01..R12` IDs
are unchanged. This addendum only adds the supplemental owners below.

ENV-00-SOURCE | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python --version`, `.venv/bin/pip-compile --version`, `.venv/bin/pip-audit --version`, `node --version` | sandbox Python 3.12.3 | 2026-09-20T19:25:23Z | 0 | PASS | `docs/audit/baseline.md` | Source toolchain only; no production services.
ENV-00-DOCKER-SANDBOX-HISTORICAL | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `docker info --format '{{.ServerVersion}}'` | restricted sandbox Docker socket | 2026-09-20 | 1 | BLOCKED | `docs/audit/baseline.md` | Historical permission denial; operator-terminal rerun is recorded below.
ENV-00-COMPOSE | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `docker compose --env-file /dev/null config -q` with fixture-only environment | sandbox Compose CLI | 2026-09-20 | 0 | PASS | `docker-compose.yml` | Config validation only; no containers or volumes.
SUP-01-C01 | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_platform_policy.py -q` | local fixture tests | 2026-09-20 | 0 | PASS | `tests/test_platform_policy.py` | 7 passed; authorization file is not a platform-contract proof.
SUP-01-C02 | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_platform_policy.py tests/test_max_gateway.py tests/test_external_action_boundaries.py -q` | local fake gateway | 2026-09-20 | 0 | PASS | `tests/test_external_action_boundaries.py` | 12 passed; no live adapter.
SUP-02-C01 | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_no_artificial_presence.py tests/test_max_gateway.py tests/test_setting_helpers.py -q` | local fake gateway/settings | 2026-09-20 | 0 | PASS | `tests/test_no_artificial_presence.py` | 9 passed; no history/read/reaction/idle/join action.
PYMAX-241-C01 | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_pymax_241_contract.py -q` | offline installed wheel | 2026-09-20 | 0 | PASS | `tests/test_pymax_241_contract.py` | 2 passed; no socket.
PYMAX-241-C02 | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_pymax_session_migration.py -q` | synthetic SQLite sessions | 2026-09-20 | 0 | PASS | `tests/test_pymax_session_migration.py` | 3 passed; no real session or network.
S02A-FOCUSED | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest -q tests/test_pymax_241_contract.py tests/test_pymax_session_migration.py tests/test_max_client_version.py tests/test_session_send_no_otp.py tests/test_cloud_password.py tests/test_wave2_high.py tests/test_max_gateway.py tests/test_no_artificial_presence.py` | local fake/fixture suite | 2026-09-20 | 0 | PASS | SDD task-4 ledger | 36 passed; no live MAX action.
S02A-DEPENDENCY | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pip check` | Python 3.12.3 venv | 2026-09-20 | 0 | PASS | `requirements.lock` | No broken requirements.
S02A-SECURITY | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/pip-audit -r requirements.lock` | Python 3.12.3 venv with approved network retry | 2026-09-20 | 0 | PASS | `docs/audit/baseline.md` | No known vulnerabilities found.
S03-RECOVERY | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_recovery_hold.py tests/test_backup_scripts.py -q` | local hold/release/backup fixtures | 2026-09-20 | 0 | PASS | `tests/test_recovery_hold.py` | 15 passed; release command is local-only.
S03-SCRIPTS | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `bash -n scripts/restore-volumes.sh scripts/verify_deploy.sh` | shell syntax only | 2026-09-20 | 0 | PASS | `scripts/restore-volumes.sh` | No restore or service execution.
S03-BROAD-PROXY | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_group_proxy_server.py -q` | sandbox asyncio/thread harness | 2026-09-20 | 130 | BLOCKED | `docs/audit/baseline.md` | Direct `asyncio.to_thread(lambda: 1)` also hangs; process interrupted safely.
SOURCE-COMPILE | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m compileall -q main.py antiban_core.py celery_worker.py app tests static` | local source tree | 2026-09-20 | 0 | PASS | source tree | Nonzero compiled source set; no network.
NODE-SYNTAX | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `node --check static/js/index.js` and `node --check static/js/admin.js` | Node v24.20.0 | 2026-09-20 | 0 | PASS | static JS | Syntax checks only.
MASTER-T00-T33 | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | normative Master V3 waves | dirty local candidate | 2026-09-20 | — | NOT RUN | plan Task 7 | No Master task is marked complete from supplemental evidence.
S04-FULL-EVIDENCE | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | full evidence/review matrix | dirty local candidate | 2026-09-20 | — | NOT RUN | plan Task 8 | Requires remaining Master waves and independent platform review.

## Continuation evidence after S04

The following rows are also dirty-worktree evidence at the same candidate SHA;
they do not close the corresponding Master consumer/integration cases.

T12-FOCUSED | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_operation_ledger_v2.py -q` | local SQLite fixture | 2026-09-20 | 0 | PASS | `tests/test_operation_ledger_v2.py` | 8 passed; isolated ledger contract, legacy campaign integration pending.
T13-FOCUSED | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_pacing_policy_v2.py -q` | local policy fixture | 2026-09-21 | 0 | PASS | `tests/test_pacing_policy_v2.py` | 11 passed; negative limits rejected; legacy worker integration pending.
T15-T33-FOCUSED | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_message_versions_v2.py tests/test_daily_plan_selection_v2.py tests/test_daily_plan_persistence_v2.py tests/test_daily_plan_worker_v2.py -q` | local SQLite fixture | 2026-09-21 | 0 | PASS | focused tests | 20 passed; round_robin and invalid-input contracts covered; upload/worker consumer integration pending.
T14-FOCUSED | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_campaign_commands_v2.py -q` | local SQLite fixture | 2026-09-20 | 0 | PASS | `tests/test_campaign_commands_v2.py` | 6 passed; HTTP handlers still require integration review.
T16-FOCUSED | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_connections_api_v2.py -q` | local fake connection catalog | 2026-09-20 | 0 | PASS | `tests/test_connections_api_v2.py` | 4 passed; no OTP/probe network.
T17-T19-FOCUSED | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_auth_ui_contract.py tests/test_panel_rate_limits_v2.py tests/test_status_service_v2.py -q` | static/fake frontend contracts | 2026-09-20 | 0 | PASS | focused tests | 9 passed; browser and route integration pending.
T20-FOCUSED | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_summary_queries_v2.py tests/test_event_loop_responsiveness.py -q` | local SQLite/event-loop fixture | 2026-09-20 | 0 | PASS | `docs/audit/performance.md` | 3 passed in 0.06s; not a real-time workload measurement.
T21-T24-FOCUSED | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_ui_review_contract.py tests/test_ui_assets_contract.py tests/test_overview_contract.py tests/test_account_filters_v2.py tests/test_admin_bulk_v2.py -q` | static frontend contracts | 2026-09-20 | 0 | PASS | focused tests | 10 passed; browser gate remains NOT RUN.
T25-FOCUSED | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_message_preview_api.py tests/test_message_versions_v2.py -q` | local SQLite/no-write fixture | 2026-09-20 | 0 | PASS | `tests/test_message_preview_api.py` | 7 passed; preview creates no schema or version and calls no MAX.
T26-FOCUSED | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_diagnostics_security_v2.py tests/test_ws_security_v2.py tests/test_security_tail.py -q` | local auth/WS fixtures | 2026-09-20 | 0 | PASS | `docs/audit/security-review.md` | 24 passed; no credentials or external socket.
T27-STATIC | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_ui_review_contract.py tests/test_ui_assets_contract.py tests/test_overview_contract.py tests/test_account_filters_v2.py tests/test_admin_bulk_v2.py -q` | static assets | 2026-09-20 | 0 | PASS | `docs/audit/ui-review.md` | 10 passed; rendered browser evidence NOT RUN.
T28-FOCUSED | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_startup_modes_v2.py -q` | local source/docs | 2026-09-20 | 0 | PASS | `docs/audit/migrations.md` | 5 passed; OpenAPI route smoke passed; Windows runtime smoke not run; Docker runtime is covered by current S05 rows.
T29-FOCUSED | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_security_regressions_v2.py tests/test_diagnostics_security_v2.py tests/test_ws_security_v2.py tests/test_security_tail.py -q` | local security fixtures | 2026-09-20 | 0 | PASS | `docs/audit/security-review.md` | 27 passed; current Docker build/DR evidence is recorded below; image CVE, VPS and policy review remain open.
T30-FULL-HOST-HISTORICAL | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `timeout 90s .venv/bin/python -m pytest tests/ -q` | restricted sandbox | 2026-09-21 | 124 | BLOCKED | `docs/audit/performance.md` | Historical host TestClient/thread lifecycle limitation; writable CI rerun is recorded below.
T30-COLLECT-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `timeout 20s .venv/bin/python -m pytest tests/ --collect-only -q` | Python 3.12.3 sandbox | 2026-09-21 | 0 | PASS | current test tree | 512 tests collected; collection is healthy, but this is not execution evidence and does not close the full regression gate alone.
T27-BROWSER | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | required 390/768/1440 browser matrix | sandbox | 2026-09-20 | — | NOT RUN | `docs/audit/ui-review.md` | Browser plugin/binary/toolchain unavailable; static tests are not browser proof.
T29-LOCKS | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/pip-audit -r requirements.lock` and `.venv/bin/pip-audit -r requirements-server.lock` | Python 3.12.3 venv, approved network retry | 2026-09-20 | 0 | PASS | `docs/audit/security-review.md` | pip-audit 2.10.1; no known vulnerabilities found.
T28-DOCKER-SANDBOX-HISTORICAL | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `docker version --format '{{.Server.Version}}'` | restricted sandbox Docker socket | 2026-09-20 | 1 | BLOCKED | `docs/audit/baseline.md` | Historical daemon permission denial; operator-terminal rerun is recorded below.
T32-S05 | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | independent final review and release gate | dirty local candidate | 2026-09-20 | — | FIX | `docs/audit/final-review.md` | Docker/full/DR are now evidenced; browser, Master, platform-authorization and production gates remain open; no production GO.

FINAL-FOCUSED-RERUN | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | combined T12-T30 focused pytest command | Python 3.12.3 sandbox | 2026-09-21 | 0 | PASS | current working tree | 87 passed; no live MAX action.
FINAL-BOUNDARY-RERUN | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | combined PyMax/gateway/hold/audit fixture pytest command | Python 3.12.3 sandbox | 2026-09-21 | 0 | PASS | current working tree | 72 passed; no live MAX action.
FINAL-STATIC-RERUN | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | compileall, Node syntax, shell syntax, diff check, JSON check, pip check, route smoke, fixture Compose config | local sandbox | 2026-09-21 | 0 | PASS | current working tree | Source/static/config checks; Docker-specific evidence is recorded in current S05 rows below.
T12-INTEGRATION-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_campaign_operation_integration_v2.py -q` | Python 3.12.3 local SQLite fake gateway | 2026-09-20T22:47:30Z | 0 | PASS | `tests/test_campaign_operation_integration_v2.py` | 15 passed; no live MAX; worker recovery, no-ACK, idempotent accounting, cancellation, midnight, retry-after and durable unknown reservation covered.
T12-LEDGER-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_operation_ledger_v2.py -q` | Python 3.12.3 local SQLite fixture | 2026-09-20T22:47:30Z | 0 | PASS | `tests/test_operation_ledger_v2.py` | 8 passed; operation identity, attempts, command receipt, provider-id and recovery contracts.
T13-INTEGRATION-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_campaign_operation_integration_v2.py tests/test_pacing_policy_v2.py tests/test_flood_wait.py -q` | Python 3.12.3 local SQLite/pacing fixtures | 2026-09-20T22:47:30Z | 0 | PASS | `app/campaign_send.py`, `main.py`, `antiban_core.py` | 28 passed; retry-after is not shortened, floor is enforced, midnight authorization date is retained; no live MAX.

## Current Wave D and S05 continuation

These rows are still dirty-working-tree evidence at the same candidate SHA;
they extend integration coverage without promoting the candidate to a
commit-bound or production verdict.

T12-T14-T15-T33-INTEGRATION-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `timeout 45s .venv/bin/python -m pytest tests/test_campaign_operation_integration_v2.py tests/test_operation_ledger_v2.py tests/test_pacing_policy_v2.py tests/test_flood_wait.py tests/test_message_versions_v2.py tests/test_message_library_integration_v2.py tests/test_message_preview_api.py tests/test_daily_plan_selection_v2.py tests/test_daily_plan_persistence_v2.py tests/test_daily_plan_worker_v2.py tests/test_daily_plan_integration_v2.py tests/test_campaign_commands_v2.py tests/test_campaign_modules.py -q` | Python 3.12.3 local SQLite/fake gateway | 2026-09-21 | 0 | PASS | current Wave D integration | 77 passed in 2.88s; daily slots carry pinned text/plan/slot identity, unknown is not replayed, proven pre-send failure may requeue, manual test uses a pinned slot, Start/Stop generation fencing is local-only.
T14-SCHEDULER-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_campaign_auto_run.py -q` | Python 3.12.3 local SQLite/tenant fixture | 2026-09-21 | 0 | PASS | `tests/test_campaign_auto_run.py` | 18 passed; scheduled start does not run proxy preflight after a persisted Stop fence; server-mode tests initialize their tenant fixture; no live MAX.
T13-REGRESSION-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_worker_phase2.py tests/test_flood_wait.py tests/test_ban_detection.py -q` | Python 3.12.3 local fake worker/gateway | 2026-09-21 | 0 | PASS | worker/flood/ban regressions | 10 passed; no live MAX.
T13-ROLE-PACING-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_role_rotation.py tests/test_role_plan_percent.py tests/test_pacing_policy_v2.py tests/test_global_pacing_settings.py -q` | Python 3.12.3 local policy fixture | 2026-09-21 | 0 | PASS | role and pacing contracts | 38 passed; product pacing values are not increased.
S05-SOURCE-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m compileall -q main.py antiban_core.py celery_worker.py app tests static` | Python 3.12.3 local source tree | 2026-09-21 | 0 | PASS | source tree | Compile check only; no network.
S05-STATIC-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `node --check static/js/index.js`; `node --check static/js/admin.js`; `bash -n scripts/restore-volumes.sh scripts/verify_deploy.sh scripts/dr-smoke.sh`; `.venv/bin/python -m json.tool verification/supplemental-acceptance-cases.json >/dev/null`; `git diff --check` | local static/config checks | 2026-09-21 | 0 | PASS | source/static/config gates | Each command exited 0; no service or volume action.
S05-DEPENDENCY-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pip check` | Python 3.12.3 venv | 2026-09-21 | 0 | PASS | `requirements.lock` | No broken requirements; installed PyMax version assertion also exited 0 for `2.4.1`.
S05-SECURITY-LOCK-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/pip-audit -r requirements.lock`; `.venv/bin/pip-audit -r requirements-server.lock` | Python 3.12.3 venv with approved network retry | 2026-09-21 | 0 | PASS | `docs/audit/security-review.md` | Both commands exited 0; no known vulnerabilities found.

## Current operator/CI rerun after runtime-proxy fix

These rows are the current dirty-worktree evidence after fixing the lazy
`app.runtime.main` assignment/deletion boundary. They are not commit-bound and
do not authorize production or live MAX actions.

ENV-00-DOCKER-OPERATOR-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `docker version --format '{{.Server.Version}}'`; `docker info --format '{{.ServerVersion}}'`; `docker compose version`; `docker buildx version` | ordinary operator terminal | 2026-09-21 | 0 | PASS | `docs/audit/baseline.md` | Docker Server 29.8.0, Compose v5.5.1, Buildx v0.37.0; no production service used.
S05-COMPOSE-CONFIG-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | fixture-env `docker compose --env-file /dev/null config -q` | isolated Compose project `maxbot-ci-gates-20260921` | 2026-09-21 | 0 | PASS | `docker-compose.yml` | Syntax/config gate only.
S05-DOCKER-BUILD-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | fixture-env `docker compose --env-file /dev/null build app` | isolated Compose project `maxbot-ci-gates-20260921` | 2026-09-21 | 0 | PASS | `Dockerfile` | Current app image built; no deploy or live MAX call.
S03-DR-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `bash scripts/dr-smoke.sh` | isolated Compose project `maxbot-ci-gates-20260921` | 2026-09-21 | 0 | PASS | `docs/audit/baseline.md` | PostgreSQL/SQLite backup-restore and verify_deploy passed; health retained `max_external_actions=held` and `recovery_hold=true`.
S05-FULL-CI-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `timeout 300s python -m pytest tests/ -q --tb=short` | writable Python 3.12 isolated CI container | 2026-09-21 | 0 | PASS | `docs/audit/performance.md` | 493 passed, 19 planned PostgreSQL skips, 6 warnings; 512 tests collected including runtime-proxy regressions.
S05-PG-MODULES-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `python -m pytest -q --tb=short tests/test_auth_remember_me.py tests/test_cross_tenant_api.py tests/test_register_rollback.py tests/test_admin_impersonation_campaign.py tests/test_db_pg_helpers.py` | writable Python 3.12 CI container plus pinned PostgreSQL 16 | 2026-09-21 | 0 | PASS | `docs/audit/performance.md` | 19 passed; 27 warnings; dedicated process prevents silent skip.
S05-E2E-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `python -m pytest -q --tb=short tests/test_e2e_server.py` | writable Python 3.12 CI container plus pinned PostgreSQL 16 | 2026-09-21 | 0 | PASS | `docs/audit/performance.md` | 4 passed; 35 warnings; no external MAX action.
S05-DEPENDENCY-CI-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `pip-audit -r requirements.lock`; `pip-audit -r requirements-server.lock` | writable Python 3.12 isolated CI container | 2026-09-21 | 0 | PASS | `docs/audit/security-review.md` | Both lockfiles reported no known vulnerabilities.
S05-SOURCE-CI-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `python -m compileall -q main.py antiban_core.py celery_worker.py app tests static`; exact installed version assertion | writable Python 3.12 isolated CI container | 2026-09-21 | 0 | PASS | `docs/audit/baseline.md` | Compile passed; `maxapi-python` is exactly 2.4.1.
S05-NODE-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `node --check static/js/index.js`; `node --check static/js/admin.js` | Node v24.20.0 | 2026-09-21 | 0 | PASS | `docs/audit/performance.md` | Static syntax only; rendered browser evidence is recorded in the commit-bound rows below.
S05-PROXY-REGRESSION-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `python -m pytest tests/test_runtime_proxy.py tests/test_campaign_auto_run.py::test_scheduler_tick_skips_expired_subscription tests/test_profile_login.py::test_profile_login_happy_path tests/test_worker_tenant_runtime.py::test_worker_start_captures_tenant_context -q` | writable Python 3.12 isolated CI container | 2026-09-21 | 0 | PASS | `app/runtime.py` | Proxy state no longer leaks between test/module reload boundaries; included in full CI run.

## Historical browser CI preparation

These rows are dirty-working-tree evidence after adding the dev-only
Playwright runner and the independent GitHub Actions job. They do not replace
hosted-CI execution or production gates.

BROWSER-CONTRACT-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `.venv/bin/python -m pytest tests/test_browser_ci_contract.py -q` | local Python 3.12 contract tests | 2026-09-21 | 0 | PASS | `tests/test_browser_ci_contract.py` | 4 passed; manifest, viewport config, provider boundary, workflow isolation and artifact contracts.
BROWSER-NPM-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `npm install --package-lock-only --ignore-scripts`; `npm ci --ignore-scripts` | Node v24.20.0/npm 11.19.0 | 2026-09-21 | 0 | PASS | `package.json`, `package-lock.json` | Exact dev-only `@playwright/test` 1.63.0 lockfile; no production dependency change.
BROWSER-HEALTH-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `curl -fsS http://127.0.0.1:8765/api/health` in bounded app fixture | isolated operator runner, temporary SQLite and recovery hold | 2026-09-21 | 0 | PASS | `app/recovery_hold.py`, `docs/audit/ui-review.md` | `ok=true`, `db_ok=true`, `recovery_hold=true`, `max_external_actions=held`.
BROWSER-MATRIX-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `npm run browser:e2e` with local fixture app | isolated operator runner with real Chromium, regular Playwright fallback | 2026-09-21 | 0 | PASS | `tests/browser/`, `playwright.config.js` | 6 passed across 390x844, 768x1024 and 1440x1000; auth/dashboard identity, focus, held state, console/request/network guard covered; no external MAX host.
BROWSER-WORKFLOW-CURRENT | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | checked-in `.github/workflows/ci.yml` `browser-e2e` job | source/static inspection; hosted runner not invoked | 2026-09-21 | — | PENDING | `.github/workflows/ci.yml` | Pinned action SHAs, Node 24, Chromium install, bounded health wait and failure artifacts are present; GitHub-hosted execution remains pending.

## Current commit-bound browser and operator evidence

The dirty-worktree rows above are retained as historical records. The
following rows are the current commit-bound evidence and supersede the
previous `BROWSER-WORKFLOW-CURRENT` pending row.

BROWSER-PR-HOSTED-CURRENT | 58da768710d761d0fbbae54581086b5073c9e289 | GitHub Actions run `35569486524` `browser-e2e` job | GitHub-hosted `ubuntu-latest` | 2026-09-21 | 0 | PASS | `https://github.com/Edifier01/maxbot/actions/runs/35569486524` | Chromium installed; local app health passed; rendered matrix reported 6 passed across 390x844, 768x1024 and 1440x1000; diagnostics artifact uploaded; no provider traffic.
BROWSER-MAIN-HOSTED-CURRENT | 4d2aa28930092e8abb2917bd004ca7a2b21c07a3 | GitHub Actions run `35571862150` push CI | GitHub-hosted `ubuntu-latest` | 2026-09-21 | 0 | PASS | `https://github.com/Edifier01/maxbot/actions/runs/35571862150` | Post-merge `main` run passed all six jobs: browser-e2e, server-smoke, server-e2e, compose-config, dependency-audit and backup-restore-smoke.
ENV-00-DOCKER-OPERATOR-RERUN | 0154884cf94d6aeccf65f5390a0f845d783c3c0e | `docker version --format '{{.Server.Version}}'` | ordinary operator terminal from dirty primary checkout | 2026-09-21 | 0 | PASS | operator terminal output | Docker Server `29.8.0`; this is environment evidence, not a clean commit-bound check; no production service or provider action.
S05-LOCAL-FULL-SANDBOX-CURRENT | 58da768710d761d0fbbae54581086b5073c9e289 | `env MAX_TEST=1 MAX_SERVER_MODE=1 JWT_SECRET=... python -m pytest tests/ -vv --maxfail=1 --durations=20` | restricted sandbox Python 3.12.3 | 2026-09-21 | 130 | BLOCKED | `docs/audit/ui-review.md` | Collection found 344 tests; five passed, then `test_admin_delete_user_quarantine.py::test_delete_user_restores_tenant_dir_if_pg_fails` blocked. Reproduction narrowed the boundary to filesystem `mkdir`/`rename` inside `asyncio.to_thread()`; hosted full regression is the writable-environment evidence.

The overall release verdict remains `FIX`: hosted browser/full regression and
the current global-upload/tenant-plan integration are evidenced, but normative
Master acceptance, independent platform authorization, secret-history/CVE
review and production gates remain open.

## Current production-readiness candidate evidence

These rows bind the latest local source candidate and supersede older dirty-
worktree summaries where the same gate was rerun. They do not authorize live
MAX, provider, VPS or production actions.

S05-CANDIDATE-FOCUSED | e4837a1fe997d63704536f01685e56b9a97caf99 | combined fake/SQLite Master safety and integration tests plus browser contract | isolated candidate with Python 3.12.3 venv | 2026-09-21 | 0 | PASS | `tests/` focused matrix | 227 passed; schema-bootstrap regression fixed; no MAX/provider traffic.
S05-CANDIDATE-FULL | e4837a1fe997d63704536f01685e56b9a97caf99 | `docker run --rm -v /tmp/maxbot-production-candidate:/workspace -w /workspace python:3.12-slim ... python -m pytest tests/ -q --tb=short` | writable Python 3.12 container | 2026-09-21 | 0 | PASS | `docs/audit/performance.md` | 497 passed, 19 planned PostgreSQL skips in 17.79s; no external MAX action.
S05-CANDIDATE-PG | e4837a1fe997d63704536f01685e56b9a97caf99 | dedicated PostgreSQL process for `tests/test_auth_remember_me.py tests/test_cross_tenant_api.py tests/test_register_rollback.py tests/test_admin_impersonation_campaign.py tests/test_db_pg_helpers.py` | pinned PostgreSQL 16 isolated Compose network | 2026-09-21 | 0 | PASS | `docs/audit/performance.md` | 19 passed; 27 warnings; no external MAX action.
S05-CANDIDATE-E2E | e4837a1fe997d63704536f01685e56b9a97caf99 | dedicated PostgreSQL process for `tests/test_e2e_server.py` | pinned PostgreSQL 16 isolated Compose network | 2026-09-21 | 0 | PASS | `docs/audit/performance.md` | 4 passed; 35 warnings; no external MAX action.
S05-CANDIDATE-SOURCE | e4837a1fe997d63704536f01685e56b9a97caf99 | compileall, Node syntax, pip check, JSON validation, `git diff --check` | isolated candidate | 2026-09-21 | 0 | PASS | source/static/config gates | All commands exited 0.
S05-CANDIDATE-DEPENDENCY | e4837a1fe997d63704536f01685e56b9a97caf99 | `pip-audit -r requirements.lock`; `pip-audit -r requirements-server.lock` | network-enabled audit runner | 2026-09-21 | 0 | PASS | `docs/audit/security-review.md` | Both reported no known vulnerabilities; no dependency changed.
S05-CANDIDATE-IMAGE | e4837a1fe997d63704536f01685e56b9a97caf99 | `docker compose --env-file /dev/null build app` | isolated Docker builder | 2026-09-21 | 0 | PASS | `Dockerfile` | Candidate image built locally; no deploy.
S05-CANDIDATE-DR | e4837a1fe997d63704536f01685e56b9a97caf99 | `COMPOSE_PROJECT_NAME=maxbot-production-candidate-ci bash scripts/dr-smoke.sh` | isolated Compose project | 2026-09-21 | 0 | PASS | `docs/audit/performance.md` | Backup/restore passed for PostgreSQL and data volume; health retained recovery hold; fixture resources were removed.
S05-CANDIDATE-BROWSER | e4837a1fe997d63704536f01685e56b9a97caf99 | `npm run browser:e2e` with bounded loopback fixture app | regular Playwright + Chromium, loopback only | 2026-09-21 | 0 | PASS | `docs/audit/ui-review.md` | 6 passed (2.1s) across 390x844, 768x1024 and 1440x1000; no external host.
S05-CANDIDATE-IMAGE-CVE | e4837a1fe997d63704536f01685e56b9a97caf99 | Docker Scout image scan | local image scanner boundary | 2026-09-21 | — | BLOCKED | `docs/audit/security-review.md` | Scanner review rejected because image/metadata may be sent to an external service; no export performed.
S05-CANDIDATE-MASTER | e4837a1fe997d63704536f01685e56b9a97caf99 | normative Master `T00..T33` acceptance | independent review boundary | 2026-09-21 | — | NOT RUN | `docs/audit/final-review.md` | Supplemental tests do not replace normative acceptance or legacy worker/HTTP integration review.

S05-CANDIDATE-BROWSER-UX | 1d50bec847d4e41c7be6b9ed13e8fb681c2a7ee2 | `npm run browser:e2e -- --reporter=line` with bounded loopback candidate app | regular Playwright + Chromium, temporary MAX_TEST fixture | 2026-09-21 | 0 | PASS | `docs/audit/ui-review.md` | 12 passed in 3.5s across 390x844, 768x1024 and 1440x1000; reduced-motion and dashboard 503 `role=alert` covered; no external host.

S05-CANDIDATE-UX-FULL | 1d50bec847d4e41c7be6b9ed13e8fb681c2a7ee2 | `timeout 600s docker run --rm -v /tmp/maxbot-production-candidate:/workspace -w /workspace python:3.12-slim ... python -m pytest tests/ -q --tb=short` | writable Python 3.12 isolated CI container | 2026-09-21 | 0 | PASS | `docs/audit/performance.md` | 497 passed, 19 planned PostgreSQL skips in 17.10s after the UX extension; no external MAX action.

S05-CANDIDATE-INTEGRATION-FINAL | 36d27c3022c6e640de28ca5dbac5fbeb58d54ace | focused global-upload/library/tenant-plan worker and command regression | Python 3.12 local SQLite/fake gateway | 2026-09-21 | 0 | PASS | `tests/test_daily_plan_integration_v2.py` | 57 passed; global message library remains global while daily plans/slots use tenant scope; no external MAX action.
S05-CANDIDATE-FULL-FINAL | 36d27c3022c6e640de28ca5dbac5fbeb58d54ace | writable Python 3.12 container `python -m pytest tests/ -q --tb=short` | isolated CI container | 2026-09-21 | 0 | PASS | `docs/audit/performance.md` | 498 passed, 19 planned PostgreSQL skips in 17.55s; no external MAX action.
S05-CANDIDATE-PG-FINAL | 36d27c3022c6e640de28ca5dbac5fbeb58d54ace | dedicated PG module and E2E process | pinned PostgreSQL 16 isolated Compose fixture | 2026-09-21 | 0 | PASS | `docs/audit/performance.md` | 23 passed; 62 warnings; temporary PG resources removed; no external MAX action.
S05-CANDIDATE-MASTER-FINAL | 36d27c3022c6e640de28ca5dbac5fbeb58d54ace | normative Master `T00..T33` and 365 acceptance cases | independent review boundary | 2026-09-21 | — | NOT RUN | `docs/audit/final-review.md` | Focused integration evidence does not replace the normative Master waves; no release GO.
S05-CANDIDATE-BROWSER-FINAL | 36d27c3022c6e640de28ca5dbac5fbeb58d54ace | `npm run browser:e2e -- --reporter=line` with bounded loopback candidate app | regular Playwright + Chromium, temporary MAX_TEST fixture | 2026-09-21 | 0 | PASS | `docs/audit/ui-review.md` | 12 passed in 3.2s across 390x844, 768x1024 and 1440x1000; no external host.
S05-CANDIDATE-DEPENDENCY-FINAL | 36d27c3022c6e640de28ca5dbac5fbeb58d54ace | `pip-audit -r requirements.lock`; `pip-audit -r requirements-server.lock` | network-enabled audit runner | 2026-09-21 | 0 | PASS | `docs/audit/security-review.md` | Both lockfiles reported `No known vulnerabilities found`; no dependency changed.
S05-CANDIDATE-IMAGE-FINAL | 36d27c3022c6e640de28ca5dbac5fbeb58d54ace | fixture-env `docker compose --env-file /dev/null build app` | isolated Docker builder | 2026-09-21 | 0 | PASS | `Dockerfile` | Current candidate image built locally; no deploy or external MAX action.
S05-CANDIDATE-DR-FINAL | 36d27c3022c6e640de28ca5dbac5fbeb58d54ace | `COMPOSE_PROJECT_NAME=maxbot-production-candidate-dr ... bash scripts/dr-smoke.sh` with fixture secrets and `DOMAIN=example.com` | isolated Compose project | 2026-09-21 | 0 | PASS | `docs/audit/performance.md` | PostgreSQL/SQLite backup-restore, stack health and `verify_deploy.sh` passed; health reported `max_external_actions=held` and `recovery_hold=true`; all temporary containers, volumes and network were removed.

The source candidate is technically green for the recorded local gates, but
the release verdict remains `FIX` until independent platform authorization,
Master acceptance, image CVE review, secret-history owner review and
production verification are separately closed.
