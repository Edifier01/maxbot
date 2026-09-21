# MAXBOT release gate

Candidate: local source commit
`1d50bec847d4e41c7be6b9ed13e8fb681c2a7ee2`.

Verdict: `FIX` for release; overall implementation handoff: `PARTIAL`.

## Evidence-bound results

- `ENV_SOURCE_READY=PASS`; Python 3.12.3 is used through `.venv/bin/python`.
- `ENV_DOCKER_READY=PASS` from the ordinary operator terminal; Docker Server
  `29.8.0`, Compose `v5.5.1`, and Buildx `v0.37.0` were verified.
- `maxapi-python==2.4.1` is pinned and installed. Verified wheel SHA-256:
  `49c996cebebdcd490b8fc1424c84faad3c33d0b75eff4bb86cf1de9d968d76ea`.
- The writable Python 3.12 CI full regression passed `497` tests with `19`
  planned PostgreSQL skips; dedicated PostgreSQL modules passed `19` and E2E
  passed `4`. Source compile, Node syntax, shell syntax, JSON, `pip check`,
  Compose config, production image build, and DR smoke also passed.
- Dependency audits for both Python locks passed with `pip-audit==2.10.1`.
- `T31` is `OFF / NOT_ADOPTED`.

## Release blockers

- Automated browser evidence at 390/768/1440, keyboard, console, failed
  network, focus and hold states is `PASS`; the current candidate also passes
  reduced-motion and recoverable dashboard-unavailable checks. Manual contrast,
  200% zoom, and the stale/loading/permission/stop-pending matrix remain
  `NOT RUN`.
- Master `T00..T33` is not closed: operation, pacing, message-library, daily-
  plan, and command services have focused contract evidence, but legacy
  worker/upload/HTTP consumer integration remains pending.
- Platform authorization, live MAX, SMS/message delivery, production/VPS, and
  secret-history owner review are not qualified. Image CVE scanning is
  blocked because the available scanner may export image metadata externally.

No real MAX action, production service, secret, push, merge, rebase, or deploy
was performed. The source candidate commit is local-only; do not treat this
`FIX` verdict as production `GO`.
