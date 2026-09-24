# T32 / S05 final review

Verdict: `FIX` for the release gate; overall remediation handoff is
`PARTIAL`. The final local source candidate is
`473eb404f374400323e9a397acb20e2818ed7637`; it is not a production approval.
The older candidate SHAs in the historical evidence below are retained as
provenance. The final commit is a local documentation/configuration
continuation on top of the reviewed runtime/test tree.

The 2026-09-22 extended local rerun passed the combined focused integration/
policy matrix (`150` tests), the full Python suite (`499 passed, 19 skipped`)
and the loopback Chromium matrix (`21 passed`). The earlier restricted-host
and restricted-Chromium attempts remain recorded as environment-specific
`BLOCKED` evidence; they do not represent application failures.

## 2026-09-23 current-worktree continuation

The active source line is baseline SHA
`716516917e393834713e63b9f51e930b332bee38`, with merge-base
`0154884cf94d6aeccf65f5390a0f845d783c3c0e` and an uncommitted worktree delta.
The historical candidate and its evidence above remain provenance; this
continuation is not a commit-bound release approval.

The earlier writable full run recorded `617 passed, 19 skipped` in `22.73s`;
the latest full-tree rerun with explicit restricted-runner compatibility
recorded `645 passed, 19 skipped` in `26.20s`. Dedicated PostgreSQL/E2E `23
passed`, loopback Chromium `78 scheduled / 44 passed / 34 expected viewport
skips`, including the revision-bound destination confirmation and readiness
preview/test-start revision-binding flows, T20 executor
`9 passed in 0.63s`, A25 ingress fixtures `16 passed`,
the A40 recovery/bootstrap contour and final runtime smoke are green (including
old-token rejection and immediate new-token acceptance), and the A45/T28 local
entrypoint smoke is green,
the structured-error UI action contour now passes `15` Python assertions and
`8` focused browser tests (all 66 catalogue codes rendered visibly on cabinet/
admin/impersonation surfaces, with every normalized action token exercised
without provider traffic),
the integrated A43 message-library fixture passes `1` local fake assertion
(import → preview → publish → frozen-slot retry with replacement-version
isolation),
the A05/R01 fake adapter-failure matrix passes `47` focused assertions,
including conservative revoked-session, rejection, wait and transport-ambiguity
handling,
the T07 auth continuation passes `25` focused Python assertions plus one
focused browser lifecycle case (two expected viewport skips), including the
historical-`needs_reauth` watcher fix and byte-preserving saved-session failure,
the T11 destination continuation passes `62` local integration assertions,
including old-route preservation and explicit revision-bound new-destination
confirmation API/UI,
and the T13 auxiliary restriction contour passes `41` local assertions,
including durable wait/ban fencing,
lockfile `pip-audit` PASS, and fresh app/PostgreSQL/Redis Compose health PASS.
The current post-boundary-flood source also rebuilt locally as manifest
`sha256:2e0ac8d899786d22cc1290624c319c34e933489023b653008df493f4dbe6466c`
with synthetic build-only placeholders; no service was started or published.
The readiness UI image rebuilt as manifest
`sha256:7f69ebfd52eb393a0c4e3da7fc4ec396a82fa1b05e1d48dfd8c47e0aceaaec60`
and passed an isolated PostgreSQL/Redis/app health smoke; no production target
or provider action was used.
The current Master execution remains
`FIX/PARTIAL`:
the 365-case acceptance, image scan, independent review, platform authorization,
production/VPS verification and live MAX/provider delivery are not closed.

## Closed locally with evidence

- `ENV_SOURCE_READY=PASS`; Python 3.12.3 and the approved tool versions are in
  `.venv`.
- `maxapi-python==2.4.1` is pinned, installed, and its wheel hash is recorded
  as `49c996cebebdcd490b8fc1424c84faad3c33d0b75eff4bb86cf1de9d968d76ea`.
- PyMax offline contract, fail-closed gateway, no artificial actions, recovery
  hold, source compile, focused regression suites, Compose validation and
  production image build, dependency audit and security boundary tests have
  concrete evidence.
- `ENV_DOCKER_READY=PASS` from the ordinary operator terminal: Docker Server
  `29.8.0`, Compose `v5.5.1`, and Buildx `v0.37.0`. The isolated DR smoke
  completed with external MAX actions held and recovery hold active.
- The writable Python 3.12 CI regression passed `498` tests with `19` planned
  PostgreSQL skips; the dedicated PostgreSQL module/E2E process passed `23`
  tests. The order-dependent runtime-proxy regression is covered by
  `tests/test_runtime_proxy.py`.
- The latest test-only UI candidate reran the same full regression and passed
  `499` tests with `19` planned PostgreSQL skips; no application source or
  production dependency changed in that extension.
- The exact candidate browser matrix passed `6` base tests across 390/768/1440,
  and the current UX extension passed `12` tests across the same viewports,
  including reduced-motion and recoverable dashboard-unavailable states. The
  isolated Docker backup/restore smoke passed with recovery hold active.
- T31 remains `OFF / NOT_ADOPTED`; no client-reuse enablement was introduced.
- Wave D continuation is locally integrated: the current 13-file operation,
  pacing, library, daily-plan and command suite passed 77 tests, and the
  campaign auto-run/scheduler suite passed 18. The scheduler now checks the
  persisted Stop fence before proxy preflight; daily worker/manual paths keep
  the pinned plan and slot identity through local fake-gateway tests.
- The server-mode global message upload now publishes the authoritative global
  library while daily plans and slots remain tenant-local; the focused
  upload/library/worker integration suite passed `57` tests, including the
  regression for this boundary.
- Structured server error envelopes now preserve their already-redacted
  `safe_message` in both user and admin frontend formatters; the exact
  candidate browser matrix passed `15` tests across 390/768/1440, including
  an unknown legacy-map code.
- The current UI contract extension passed `4` focused tests, and the
  loopback-only Chromium matrix passed `21` tests across 390/768/1440,
  including semantic-token WCAG AA checks and a 195x422
  200%-equivalent reflow check for auth/dashboard surfaces.
- The extended local runner reran the final tree: `499` Python tests passed,
  `19` planned PostgreSQL tests were skipped, and all `21` browser tests passed
  across 390/768/1440 without external MAX/provider traffic.

## Release blockers

- A true browser 200% zoom session, full rendered contrast review, and the complete
  loading/permission/stale/stop-pending matrix remain `NOT RUN`; reduced-motion
  and recoverable dashboard-unavailable behavior, semantic token contrast and
  narrow reflow have automated evidence. The automated rendered browser gate is
  PASS at 390/768/1440.
- Master `T00..T33` acceptance is not closed by supplemental contracts or the
  required 365-case normative waves. The global-upload → tenant-library →
  daily-plan worker boundary is now covered by focused integration evidence,
  but the broader Master consumer/HTTP matrix remains unexecuted. The
  canonical Master file and its expected SHA-256 are now locally verified;
  this is source provenance, not acceptance execution.
- Platform authorization underlying evidence, production/VPS, live MAX and
  SMS/message delivery are `BLOCKED/NOT RUN` by authorization and safety rules.
- At initial review image vulnerability scanning was blocked pending approval
  for external image-metadata transfer. That approval was subsequently given
  for exact local digests and scans were run; the latest image still has
  unresolved findings, so image security remains open. Protected-branch and
  secret-history owner review also remain open despite a pinned image build
  and clean Python lockfile audits.
- Secret-history regex matches in historical `server/skills/...` revisions
  require owner review without reproducing any values; this is not treated as
  a clean secret-history PASS.

## Explicit invariants reviewed

The review found no intentional change to active/quiet/skip policy values,
working windows, warmup/lazy-day, personal plan semantics, reusable library
intent, one-work-group rule, persistent account route, sender identity, or
product limits. Unknown external outcomes are not automatically replayed in
the new ledger contracts. No artificial presence, auto-join, proxy reshuffle,
sender substitution, speed increase, or official Bot API path was added.

This review does not claim absence of account blocking, successful delivery, or
production readiness. The remaining gates are independent platform-
authorization review, unexecuted normative Master acceptance, image CVE review,
secret-history ownership, and production verification; no real MAX action may
run unless separately authorized.

## 2026-09-24 bounded local continuation

The source remains base SHA `716516917e393834713e63b9f51e930b332bee38`
with a dirty worktree; no commit-bound review was performed. Fresh current-tree
regression passed `690` tests with `19` planned PostgreSQL skips in `29.95s`;
dedicated PostgreSQL modules and server E2E passed `19` and `4` respectively.
Compileall, exact `maxapi-python==2.4.1`, Node syntax, fixture Compose config,
`git diff HEAD --check`, and both read-only lockfile audits passed. A new
isolated backup/restore smoke restored PostgreSQL and tenant-data markers,
then confirmed `ok/db_ok/server_mode=true`, `max_external_actions=held`, and
`recovery_hold=true`; Caddy/host-published ports were disabled for this test.
Focused T26 export/toast browser checks passed at 390x844 and toast flow at
1440x1000; the broader synthetic matrix remains `57 passed, 30 expected
viewport-bound skips` from `87` scheduled cases.

Disposition remains `FIX / PARTIAL`, not GO: the normative 365-case Master
acceptance is incomplete; T30-C02 aligned performance comparison and T08-C04
Windows lock coverage are `NOT RUN`; underlying company platform authorization,
human secret-history review, image CVE findings, native/manual accessibility,
and production/VPS verification remain open. The latest user-authorized Docker
Scout scan covered `sha256:507c54a787760210eecf19d51ffafb8354990f0f78fa326e891b1e5054a4f2e9`
and found 29 vulnerabilities (0 critical, 2 high, 2 medium, 25 low). The
runtime image now removes pip; local non-root/import checks and the Dockerfile
test passed. The checkout is intentionally left uncommitted, so no independent
exact-commit review or commit-bound verdict is claimed. No MAX, provider, SMS,
production, push, merge, or deploy action occurred.

## 2026-09-24 T08 and image-scan continuation

The current dirty candidate remains base SHA
`716516917e393834713e63b9f51e930b332bee38`, with no commit-bound review.
After the T08 quarantine fix, the focused deletion tests passed (`4 passed`),
the full SQLite suite passed (`693 passed, 19 skipped`), and a fresh loopback,
tmpfs-only PostgreSQL server E2E run passed (`4 passed`), including successful
tenant deletion. A Windows Python 3.14.1 OS-level lock probe reproduced the
previous false-success behavior and confirmed strict `rmtree` fails safely;
full native Windows app tests remain unavailable. T08-C04 is PASS only for this
bounded evidence.

The exact user-authorized image `sha256:aeac47f0eb2c427e4c1bee78e4df3edb3410c69383da4e587ced4ba04e414951`
was scanned by Docker Scout: 29 findings (0 critical, 2 high, 2 medium, 25
low); the two high Debian perl/zlib entries show no fixed version. The image
gate remains FIX/PARTIAL. T30-C02's aligned benchmark and the 365-case Master
acceptance remain incomplete, so overall disposition is still `FIX / PARTIAL`,
not GO. No image publication, commit, push, provider, MAX, production, or deploy
action occurred.
