# MAXBOT supplemental baseline

## Current continuation (2026-09-22)

The historical baseline below was captured from `0154884cf94d6aeccf65f5390a0f845d783c3c0e`.
The current runtime/test continuation is
`473eb404f374400323e9a397acb20e2818ed7637`; its focused integration and UI
changes are described in `docs/audit/final-review.md` and
`docs/audit/verification.md`. Historical rows are not silently relabeled as
evidence for the newer SHA.

Дата baseline: 2026-09-20. Это dirty-worktree evidence; commit-bound и
production verdict не заявляются.

## Source and environment

- Original and current `HEAD`: `0154884cf94d6aeccf65f5390a0f845d783c3c0e`.
- Working tree: dirty; existing user-owned `docs/audit/` and plan files were
  preserved; no commit, push, merge, rebase, or deploy was performed.
- Main audit source SHA-256: `8c7a57092be519ea5df0379abc6030124d1e099867adbc72a06174027c90392d`.
- `ENV_SOURCE_READY=PASS`: Python 3.12.3, `pytest 9.1.1`,
  `pip-tools 7.6.1`, `pip-audit 2.10.1`, Node `v24.20.0`.
- `ENV_DOCKER_READY=PASS` from the ordinary operator terminal: Docker Server
  `29.8.0`, Compose `v5.5.1`, Buildx `v0.37.0`; both
  `docker version --format '{{.Server.Version}}'` and
  `docker info --format '{{.ServerVersion}}'` exited 0.
- Fixture-only `docker compose --env-file /dev/null config -q` exited 0.
- The isolated CI Compose project built the app image and completed the DR
  smoke; its health response remained `max_external_actions=held` and
  `recovery_hold=true`.

## Dependency and PyMax contract

- `maxapi-python==2.4.1` is installed and pinned in `requirements.txt` and
  `requirements.lock`; `requirements-server.lock` was not changed.
- Verified wheel SHA-256:
  `49c996cebebdcd490b8fc1424c84faad3c33d0b75eff4bb86cf1de9d968d76ea`.
- The contract tests verify `Client.connect()` is coroutine, the pinned
  `ExtraConfig.generate_user_agent(self, app_version, build_number)` shape,
  and the `Client.send_message` provider `Message` return type.
- Runtime policy is explicit: `api2.oneme.ru:443`,
  `VersionCatalog(remote=False)`, `reconnect=False`, `relogin=False`,
  `telemetry=False`, `persist_session=True`.
- `pip check` and `pip-audit -r requirements.lock` passed; no known
  vulnerabilities were reported for the main lock.

## Scope status

- `S00`, `S01`, `S02`, `S02A`, and `S03` have focused evidence recorded in
  `verification.md` and the SDD ledger.
- `AUD20-A01..A46` and `COMP-R01..R12` remain Master requirements; this
  baseline does not mark them closed merely because supplemental tests pass.
- Master `T00..T33` have not yet been executed in their normative waves.
- Supplemental `SUP-01..SUP-03` and `PYMAX-241-C01/C02` have PASS evidence,
  but it is dirty-worktree evidence, not commit-bound acceptance.
- `MAX_PLATFORM_AUTHORIZATION_FILE=UNSET`: platform authorization state is
  `ABSENT` for this local run. No authorization record contents are copied
  here, and live verification is `BLOCKED`.

## Safety and limitations

- No real SMS, login, send, join, probe, history, read, reaction, MAX socket,
  production secret, proxy credential, session cookie, or production service
  was used.
- Synthetic session fixtures contain only fixture values and are created under
  temporary paths. The S02A migration is offline and preserves token/device/
  phone/sync fields without logging them.
- The host `.venv` still has a `TestClient`/thread lifecycle hang in this
  sandbox, but the same source was executed in a writable Python 3.12 CI
  container: the full SQLite suite and the separate PostgreSQL/E2E processes
  completed successfully. The host limitation is retained as a local-harness
  note, not promoted to a CI failure.
- Production/VPS, live platform authorization review, full Master acceptance,
  image CVE scanning, and production verification remain `NOT RUN` or
  `BLOCKED` as stated in `verification.md`; the current automated browser
  matrix is now separately evidenced as `PASS`.

## Current source revalidation

On 2026-09-21 the canonical Master source was re-read from
`/mnt/c/Users/Edifi/Documents/MAXBOT_MASTER_V3_EN_2026-09-20.md`.
`sha256sum` returned the expected
`8c7a57092be519ea5df0379abc6030124d1e099867adbc72a06174027c90392d`, and a
deterministic heading parser counted `365` acceptance cases. This validates
source availability and provenance only; it does not turn the normative waves
into PASS.
