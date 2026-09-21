# T30 regression and performance evidence

Status: `PASS` for the required full regression gate on source candidate
`36d27c3022c6e640de28ca5dbac5fbeb58d54ace` in an isolated writable Python
3.12 CI container; the separate reference performance workload gate remains
`NOT RUN`.

## Current regression execution

| Command | Result |
|---|---|
| `docker run --rm -v /tmp/maxbot-production-candidate:/workspace -w /workspace python:3.12-slim ... python -m pytest tests/ -q --tb=short` | PASS, exit 0; `498 passed, 19 skipped in 17.55s` on source candidate `36d27c3022c6e640de28ca5dbac5fbeb58d54ace` |
| PostgreSQL modules and E2E auth/admin/tenant | PASS, exit 0; 23 passed in one separate process against pinned PostgreSQL 16 |
| `python -m compileall -q main.py antiban_core.py celery_worker.py app tests static` | PASS, exit 0 in the same CI container |
| `node --check static/js/index.js` and `node --check static/js/admin.js` | PASS, exit 0 |

The final source commit `36d27c3022c6e640de28ca5dbac5fbeb58d54ace` reran the
writable full suite after the global-library/tenant-plan integration fix with
`498 passed, 19 skipped in 17.55s`. The skipped PostgreSQL modules and E2E
process passed `23` tests against pinned PostgreSQL 16.

The 19 skips in the SQLite process are the CI-designated PostgreSQL modules;
they are not treated as required skips because the modules and E2E suite passed
in their dedicated PostgreSQL processes. No MAX network or external action was
used.

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
