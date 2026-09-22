# MAXBOT release gate

Candidate runtime/test commit:
`266022fe39a05c978b738565633e714047bc740e`.

Historical evidence rows retain the SHAs on which those checks actually ran;
the documentation/configuration reconciliation is a local continuation.

Fresh 2026-09-22 focused integration/policy checks passed (`150`),
while the restricted host full suite and local Chromium launch are `BLOCKED`
by environment boundaries. This does not replace writable CI or production
verification.

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
