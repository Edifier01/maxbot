# T30 regression and performance evidence

Status: `PASS` for the required full regression gate in the isolated writable
Python 3.12 CI environment; the separate rendered-browser and reference
performance workload gates remain `NOT RUN`.

## Current regression execution

| Command | Result |
|---|---|
| `timeout 300s python -m pytest tests/ -q --tb=short` | PASS, exit 0; `493 passed, 19 skipped` from 512 collected on 2026-09-21 in a writable Python 3.12 container |
| PostgreSQL skipif modules | PASS, exit 0; 19 passed in a separate process against pinned PostgreSQL 16 |
| PostgreSQL E2E auth/admin/tenant | PASS, exit 0; 4 passed in a separate process |
| `python -m compileall -q main.py antiban_core.py celery_worker.py app tests static` | PASS, exit 0 in the same CI container |
| `node --check static/js/index.js` and `node --check static/js/admin.js` | PASS, exit 0 |

The 19 skips in the SQLite process are the CI-designated PostgreSQL modules;
they are not treated as required skips because the modules and E2E suite passed
in their dedicated PostgreSQL processes. No MAX network or external action was
used.

## Historical local-harness limitation

The host `.venv` run remains bounded by the sandbox's `TestClient`/thread
lifecycle hang and exited 124. It is retained as a limitation, but it is not a
failure of the authoritative writable CI run. The prior 485/510 collection
counts and timeout evidence are historical and superseded by the current CI
rows above.

Historical host evidence: the bounded run ended with `exit 124`; that result is
not converted into a PASS and is not used to override the current CI result.

The historical host timeout is not converted into a PASS and the hanging test
is not silently skipped; it is explicitly superseded by the successful
writable CI execution above.

## Performance workload

The Master reference workload (ten tenants, one hundred synthetic accounts per
tenant, ten subscribers, two tabs and WebSocket outage/hidden-tab cases) is
`NOT RUN`: rendered browser evidence and the full reference workload are not
available in this run. The local event-loop responsiveness tests are
fixture-level checks, not a real-time production or MAX measurement. No
request-rate increase or parallel sender was introduced.

## Optional bounded client reuse

T31 is `OFF / NOT_ADOPTED`. No client reuse feature or enablement flag was
introduced; stable session identity and explicit route lifecycle remain the
safer default.
