# T30 regression and performance evidence

Status: `PASS` for the previously recorded writable-CI regression evidence;
the current runtime/test continuation is
`473eb404f374400323e9a397acb20e2818ed7637`.
The separate reference performance workload gate remains `NOT RUN`, and the
historical rows below retain the SHAs on which those checks actually ran.

The restricted host rerun on 2026-09-22 collected `518` tests and timed out at
`test_admin_delete_user_quarantine.py::test_delete_user_restores_tenant_dir_if_pg_fails`
after 10 passes because the restricted filesystem/`asyncio.to_thread()`
boundary did not return. An extended local runner then completed the final
candidate with `499 passed, 19 skipped`; the restricted result remains a
harness limitation and historical writable-CI PASS rows retain their own
SHAs.

## Current regression execution

## 2026-09-24 dirty-candidate continuation

Candidate base: `716516917e393834713e63b9f51e930b332bee38`; all results below
are current dirty-worktree evidence, not commit-bound acceptance.

| Gate | Result |
|---|---|
| Full Python suite | `690 passed, 19 skipped in 29.64s`; the skipped modules are PostgreSQL-dependent and remain disclosed, not counted as PASS in this invocation |
| Dedicated PostgreSQL modules + server E2E | `19 passed` + `4 passed` against pinned PostgreSQL 16 in a disposable tmpfs-only local container; 62 Starlette deprecation warnings, no failures; the container was auto-removed |
| Targeted T30 daily-plan/library/worker cases | `3 passed`; two target-five accounts retain the shared five-item library over ten accepted slots, restart preserves selections, and the worker may claim an already-queued slot |
| Two-tab local API/WebSocket window | `PASS` at `390x844`; two tabs, 60 seconds, 26 API responses, no `429`, no repeated status GET while both WebSockets were healthy, no browser errors or external requests |
| Current image build | `PASS`; final BuildKit manifest list `sha256:4e9379836059516aa61039d0a78020f7d3e136ea8d71fe4c0512bc2b0d4b4927`; `--pull=false`, synthetic values, no image push |
| Final local Compose runtime smoke | `PASS` for app/PostgreSQL/Redis health; `db_backend=postgres`, recovery hold active, no published app port or startup exception; exact image manifest `sha256:4e9379836059516aa61039d0a78020f7d3e136ea8d71fe4c0512bc2b0d4b4927`; temporary project resources removed |
| Focused rendered UI checks | Playwright `2 passed` at `390x844` (safe auth-attempt preview/download and toast flow), `1 passed` at `1440x1000` (toast flow); screenshots stored under `/tmp/maxbot-t26-*` |
| Static/config checks | `PASS`; compileall, all shell/JS syntax checks, `pip check`, Compose config with synthetic values, staged and unstaged `git diff --check` |

The Master reference workload is still `NOT RUN`: there is no aligned
before/after baseline and candidate workload recording the required dataset,
host, five repetitions, p50/p95, SQL counts, CPU/RSS, event-loop lag and
subscriber/hidden-tab/WebSocket-outage cases. No performance improvement
percentage is claimed. The latest Python invocation skipped 19 PostgreSQL
modules; the separately recorded PostgreSQL run is historical evidence and is
not represented as a rerun against this exact dirty delta.

## 2026-09-24 T08 continuation

The latest full SQLite suite is `693 passed, 19 skipped in 31.89s`; the new
T08 focused deletion tests are `4 passed`, and a fresh disposable PostgreSQL
server E2E run is `4 passed` (including successful admin tenant deletion).
An isolated Windows Python 3.14.1 OS probe reproduced the locked-file false
success from `rmtree(ignore_errors=True)` and verified strict deletion raises
without removing the locked file. These are safety regressions, not performance
measurements. T30-C02 remains `NOT RUN`; no aligned five-repetition baseline
comparison was created.

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
production or MAX measurement. Session-cache hits now perform a durable
revocation lookup for each authenticated request (including each WebSocket
status read); this increases database read volume versus the former cache-only
path. The reference workload and resulting throughput/latency impact remain
`NOT RUN` / unmeasured. No parallel sender was introduced.

## Optional bounded client reuse

T31 is `OFF / NOT_ADOPTED`. No client reuse feature or enablement flag was
introduced; stable session identity and explicit route lifecycle remain the
safer default.
