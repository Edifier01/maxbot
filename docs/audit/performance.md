# T30 regression and performance evidence

Status: `PASS` for the previously recorded writable-CI regression evidence;
the current runtime/test continuation is `266022fe39a05c978b738565633e714047bc740e`.
The separate reference performance workload gate remains `NOT RUN`, and the
historical rows below retain the SHAs on which those checks actually ran.

The fresh host rerun on 2026-09-22 collected `518` tests and then timed out at
`test_admin_delete_user_quarantine.py::test_delete_user_restores_tenant_dir_if_pg_fails`
after 10 passes because the restricted filesystem/`asyncio.to_thread()`
boundary did not return. The current host result is `BLOCKED`; historical
writable-CI PASS rows remain bound to their original SHAs.

## Current regression execution

| Command | Result |
|---|---|
| `docker run --rm -v /tmp/maxbot-production-candidate:/workspace -w /workspace python:3.12-slim ... python -m pytest tests/ -q --tb=short` | PASS, exit 0; `498 passed, 19 skipped in 15.68s` on source candidate `c5f52980dd7297d97ad440efe8a0fdf94997fb1b` |
| PostgreSQL modules and E2E auth/admin/tenant | PASS, exit 0; 23 passed in one separate process against pinned PostgreSQL 16 |
| `python -m compileall -q main.py antiban_core.py celery_worker.py app tests static` | PASS, exit 0 in the same CI container |
| `node --check static/js/index.js` and `node --check static/js/admin.js` | PASS, exit 0 |
| `COMPOSE_PROJECT_NAME=maxbot-production-candidate-dr ... bash scripts/dr-smoke.sh` | PASS, exit 0; isolated PostgreSQL/SQLite backup-restore and `verify_deploy.sh`; fixture resources removed |

The latest test-only UI candidate `24b75c3fd87385ff1af7e2284d581a9a0b558215`
also reran the full suite in a Python 3.12 container using a read-only mount
of the installed candidate environment: `499 passed, 19 skipped in 16.09s`.
The additional count is the new UI contrast contract; application behavior and
the previously recorded image/DR evidence were unchanged.

The final source commit `c5f52980dd7297d97ad440efe8a0fdf94997fb1b` reran the writable full suite after the
structured safe-error rendering fix with `498 passed, 19 skipped in 15.68s`.
The skipped PostgreSQL modules and E2E
process passed `23` tests against pinned PostgreSQL 16.

The 19 skips in the SQLite process are the CI-designated PostgreSQL modules;
they are not treated as required skips because the modules and E2E suite passed
in their dedicated PostgreSQL processes. No MAX network or external action was
used.

The final isolated DR-smoke used only fixture secrets and `DOMAIN=example.com`
to avoid an external TLS/DNS probe. It completed the backup/restore cycle,
stack health and deployment verification; health retained
`max_external_actions=held` and `recovery_hold=true`. The cleanup trap removed
all temporary containers, volumes and network. This is recovery evidence only,
not production deployment proof.

## Historical local-harness limitation

The host `.venv` run remains bounded by the sandbox's `TestClient`/thread
lifecycle hang and exited 124/130 in separate attempts. It is retained as a
limitation, but it is not a failure of the authoritative writable CI run. The
prior 485/510 collection counts and timeout evidence are historical and
superseded by the current CI rows above.

Historical host evidence: the bounded run ended with `exit 124`; that result is
not converted into a PASS and is not used to override the current CI result.
That bounded run recorded 515 collected on 2026-09-21 before the sandbox
lifecycle block.

The historical host timeout is not converted into a PASS and the hanging test
is not silently skipped; it is explicitly superseded by the successful
writable CI execution above.

## Performance workload

The Master reference workload (ten tenants, one hundred synthetic accounts per
tenant, ten subscribers, two tabs and WebSocket outage/hidden-tab cases) is
`NOT RUN`: the full reference workload is not available in this run. The
rendered browser gate is separately PASS in `docs/audit/ui-review.md`. Local
event-loop responsiveness tests are fixture-level checks, not a real-time
production or MAX measurement. No request-rate increase or parallel sender was
introduced.

## Optional bounded client reuse

T31 is `OFF / NOT_ADOPTED`. No client reuse feature or enablement flag was
introduced; stable session identity and explicit route lifecycle remain the
safer default.
