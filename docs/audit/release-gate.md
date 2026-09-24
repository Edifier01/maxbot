# MAXBOT release gate

Candidate runtime/test commit:
`473eb404f374400323e9a397acb20e2818ed7637`.

Historical evidence rows retain the SHAs on which those checks actually ran;
the final documentation/configuration reconciliation is a local continuation.

Fresh 2026-09-22 extended local checks passed: focused integration/policy
(`150`), full Python (`499 passed, 19 skipped`) and loopback Chromium (`21`).
Restricted-sandbox failures remain recorded as environment-specific evidence;
this does not replace normative, production or live-provider verification.

Current-worktree continuation on 2026-09-24: baseline
`716516917e393834713e63b9f51e930b332bee38` reconciled to merge-base
`0154884cf94d6aeccf65f5390a0f845d783c3c0e`, still dirty and not
commit-bound. The earlier writable full rerun is `617 passed, 19 skipped` in
`22.73s`; the latest full-tree compatibility rerun is `684 passed, 19
skipped` in `29.55s` with opt-in test-only thread and uvloop runner support;
the prior `633 passed` run remains historical evidence.
Dedicated PostgreSQL modules and E2E were freshly rerun on the same dirty
candidate at `19 passed` + `4 passed` (62 Starlette deprecation warnings, no
failures) against a disposable tmpfs-only PostgreSQL 16; the latest loopback
browser matrix is `57 passed` with `30` expected viewport-bound skips from
`87` scheduled cases, including
the revision-bound destination confirmation and readiness preview/test-start
revision-binding flows; T20 executor responsiveness is `9
passed in 0.63s`, A25 ingress fixtures are `16 passed`, A40 recovery/bootstrap
and immediate JWT invalidation/reissue are locally green; A45/T28 local
startup, health and metrics are also green, and fresh
app/PostgreSQL/Redis Compose health is green. These are
continuation evidence only and do not change the `FIX/PARTIAL` release verdict
below.

The current structured-error UI continuation also passes `15` focused Python
assertions and `8` focused browser tests on `390x844` (with the expected
viewport-bound skips elsewhere): all 66 catalogue codes render visible safe
action controls on cabinet/admin/impersonation surfaces, and every normalized
action token opens only local review/authentication surfaces without provider
traffic. The integrated A43 message-library fixture also passes `1` local fake
assertion for import → preview → publish → frozen-slot retry, including
replacement-version isolation. The A05/R01 adapter-failure matrix is also
green at `47` focused fake/fixture assertions; no provider action was used.
The T07 auth continuation is green at `25` focused Python assertions plus one
focused browser lifecycle case (two expected viewport skips), including the
active-attempt-over-historical-`needs_reauth` watcher fix and byte-preserving
saved-session failure. The T11 destination continuation is green at `62`
local integration assertions, including the revision-bound confirmation
API/UI, and the T13 auxiliary restriction contour is
green at `41` local assertions; both remain fixture-only evidence.
The current post-boundary-flood source rebuilt locally as manifest
`sha256:2e0ac8d899786d22cc1290624c319c34e933489023b653008df493f4dbe6466c`
with synthetic build-only placeholders; no service was started or published.
The readiness UI image rebuilt as manifest
`sha256:7f69ebfd52eb393a0c4e3da7fc4ec396a82fa1b05e1d48dfd8c47e0aceaaec60`
and passed an isolated PostgreSQL/Redis/app health smoke; no production target
or provider action was used.

Verdict: `FIX` for release; overall implementation handoff: `PARTIAL`.

## Evidence-bound results

- `ENV_SOURCE_READY=PASS`; Python 3.12.3 is used through `.venv/bin/python`.
- `ENV_DOCKER_READY=PASS` from the ordinary operator terminal; Docker Server
  `29.8.0`, Compose `v5.5.1`, and Buildx `v0.37.0` were verified.
- `maxapi-python==2.4.1` is pinned and installed. Verified wheel SHA-256:
  `49c996cebebdcd490b8fc1424c84faad3c33d0b75eff4bb86cf1de9d968d76ea`.
- The writable Python 3.12 CI full regression passed `498` tests with `19`
  planned PostgreSQL skips; the dedicated PostgreSQL module/E2E process passed
  `23`. Source compile, Node syntax, shell syntax, JSON, `pip check`,
  Compose config, production image build, and DR smoke also passed.
- The latest test-only UI candidate reran the full regression and passed `499`
  tests with `19` planned PostgreSQL skips; the application source and image
  contents were unchanged by that extension.
- Dependency audits for both Python locks passed with `pip-audit==2.10.1`.
- `T31` is `OFF / NOT_ADOPTED`.
- The user/admin frontend preserves server-provided redacted `safe_message`
  values; the exact candidate browser matrix passed `15` tests.
- The current error catalogue continuation preserves redacted metadata, renders
  all 66 codes visibly on cabinet/admin/impersonation surfaces, and invokes
  every normalized action without automatic retry or MAX/provider traffic;
  unknown-send and terminal rejected-send paths persist only fixed safe
  messages for synthetic exception sentinels while retaining retry and ban
  controls; bulk profile-import row failures and dashboard/server-log storage
  failures now return safe structured error metadata without exception text in
  application logs; legacy send-log error values are redacted when read and
  returned with safe action metadata. Other API/WebSocket/cache/export
  consumers and independent/manual acceptance remain open.
- The current UI extension passed `4` focused token/asset contracts and `21`
  loopback-only browser tests, including 195x422 200%-equivalent reflow for
  auth/dashboard surfaces.

## Release blockers

- Automated browser evidence at 390/768/1440, keyboard, console, failed
  network, focus and hold states is `PASS`; the current candidate also passes
  reduced-motion, recoverable dashboard-unavailable, semantic-token contrast,
  and 195x422 reflow checks. A true browser 200% zoom session, full rendered
  contrast review, and the stale/loading/permission/stop-pending matrix remain
  `NOT RUN`.
- Master `T00..T33` is not closed: operation, pacing, message-library, daily-
  plan, and command services have focused contract and current global-upload →
  tenant-plan integration evidence, but the normative 365-case Master and
  broader HTTP consumer waves remain pending. The canonical source checksum
  and all 365 case headings are now locally verified; no case is marked PASS
  from that inventory alone.
- Platform authorization, live MAX, SMS/message delivery, production/VPS, and
  secret-history owner review are not qualified. Image CVE scanning is
  blocked because the available scanner may export image metadata externally.

No real MAX action, production service, secret, push, merge, rebase, or deploy
was performed. The source candidate commit is local-only; do not treat this
`FIX` verdict as production `GO`.

## 2026-09-24 current dirty-worktree recheck

The base commit remains `716516917e393834713e63b9f51e930b332bee38`; the
current worktree is still dirty and therefore not a commit-bound candidate.
Fresh Python regression: `690 passed, 19 skipped` (the PostgreSQL modules were
run separately: `19 passed`; server E2E: `4 passed`). Compileall, exact PyMax
pin, Node syntax, fixture Compose config, both lockfile audits, and an isolated
backup/restore smoke passed. The DR smoke restored database and tenant-data
markers and retained the external recovery hold; its unique project and volumes
were removed. The narrow current-attempt diagnostic export and toast-flow UI
checks also passed their local API/browser fixtures, while T26/T27 remain
PARTIAL.

The release gate remains `FIX / PARTIAL`: the 365 normative acceptance cases
and T30-C02 reference performance run are not complete; platform authorization
and consent have no independently reviewable source record; manual accessibility
review, secret-history ownership review and production/VPS qualification remain
open. T08-C04 now has bounded local evidence: an isolated Windows 3.14.1
filesystem-lock probe, route-level Linux failure injection, `4` focused deletion
tests, and the PostgreSQL server E2E deletion flow (`4 passed`). This is not a
full native Windows application test run. The user-authorized Docker Scout scan
of the exact current local image `sha256:aeac47f0eb2c427e4c1bee78e4df3edb3410c69383da4e587ced4ba04e414951`
found 29 vulnerabilities (0 critical, 2 high, 2 medium, 25 low); two high
Debian package findings have no fixed version listed. Image security remains
FIX/PARTIAL pending vendor fixes or owner risk disposition. The current SQLite
suite passed `693` with `19` PostgreSQL skips; PostgreSQL server E2E separately
passed `4`. Git commit/push, deployment and live provider qualification were not
performed. This continuation is local evidence only, not the required
independent exact-SHA review.
