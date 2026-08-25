# MAX Sender — production readiness ledger

**Дата:** 2026-08-25  
**Решение:** **NO-GO** до закрытия external gates ниже.

## Release identity

| Поле | Значение |
|---|---|
| Branch | `codex/production-readiness-wave2` |
| Проверенный code HEAD до ledger-only commit | `95148e4809084ea09c449ca2a3846426042e3df9` |
| `main` / merge base с `main` | `16d0ce08e2f69dc1b26b847b2bc3c2b349d86959` |
| Merge base с `origin/main` | `9d16c62457eef20840f01dc5eec3f33d815d1d91` |
| Remote | `https://github.com/Edifier01/maxbot.git` |
| Delta к `origin/main` на проверенном HEAD | `0 behind / 27 ahead` |
| Tracked/index state | clean |
| Полный worktree state | dirty: только два untracked pytest basetemp (`.pytest-production-final-1/`, `.pytest-production-final-2/`) |

SHA commit, содержащего этот ledger, нельзя записать внутрь самого commit без
изменения SHA. Перед push release executor обязан заново выполнить
`git rev-parse HEAD`, `git status --short --untracked-files=all` и использовать
полученный финальный SHA во всех GitHub/VPS evidence.

## Frozen scope

В stages 1–3 не менялись: anti-ban; human timing/pauses/limits/windows;
warmup/cooldown; роли и проценты ролей; local-day semantics; global settings;
`worker_pool_size`; production credentials и внешние сервисы. Runtime diff этой
волны — test-only. Остальные изменения ограничены CI, deploy/verify/DR scripts
и документацией.

## Reconciliation F-P1-01…08

| Finding | Статус | Repository evidence | Оставшийся gate |
|---|---|---|---|
| F-P1-01 duplicate send after cancel | CLOSED | `app/campaign_send.py` (`SendTracker`), `app/campaign_worker.py::_maybe_return_to_bag`, `tests/test_campaign_send_cancel.py` | GitHub/Linux full suite на финальном SHA |
| F-P1-02 signal skips worker drain | CLOSED | `app/shutdown.py::graceful_shutdown`, `tests/test_shutdown_handler.py::test_shutdown_drains_workers_before_encrypting_sessions` | Staging SIGTERM/restart observation |
| F-P1-03 CI differs from shipped locks | CLOSED | `.github/workflows/ci.yml` installs `requirements.lock`, `requirements-server.lock`, `requirements-dev.txt`; separate `dependency-audit` | GitHub jobs green on final SHA |
| F-P1-04 automatic/weak deploy | CLOSED | manual `workflow_dispatch`, production environment, reusable full CI, exact-SHA checkout, non-empty SSH fingerprint gate, shared `scripts/deploy.sh` | Protected environment and correct production secrets verified |
| F-P1-05 inconsistent hot backup | CLOSED | `scripts/backup-volumes.sh` stops writers/checkpoints/verifies; `scripts/dr-smoke.sh` restores after stopping PostgreSQL | Docker CI plus production-like migration/restore rehearsal |
| F-P1-06 SQLite connection shared across threads | CLOSED | thread-keyed connections in `app/sqlite_backend.py`; `test_server_sqlite_connection_is_scoped_per_thread` | Linux CI; production pool values still separately constrained below |
| F-P1-07 missing orphan helper | CLOSED | `app/routes_groups.py::_delete_orphan_profile`; atomic regression in `tests/test_audit_fixes.py` | GitHub full suite |
| F-P1-08 tenant log falls back to global buffer | CLOSED | `app/routes_dashboard.py` returns 503 on tenant-log failure; fail-closed regression in `tests/test_audit_fixes.py` | GitHub full suite |

Закрытие старых P1 в repository не означает production GO: frozen defects и
environment gates ниже остаются блокирующими.

## Stages 1–3 evidence

### Stage 1 — baseline and root cause

- Fresh isolated baseline: `1 failed, 266 passed, 20 skipped in 177.28s`.
- Failure: `tests/test_flood_wait.py::test_send_with_retry_sleeps_flood_wait`.
- Teardown tracing disproved the campaign fixture hypothesis. Root cause was
  cached `app.config.MAX_SERVER_MODE`; the flood-wait test changed env after
  import. Test-only fix patches the existing `main._is_server_mode` boundary.
- Focused evidence after fix: ordered pair `5 passed`; complete campaign and
  flood-wait modules `6 passed`.

### Stage 2 — non-frozen remediation

- Cancel after acknowledged send: `1 passed`; mutation of `may_requeue` failed
  as expected. In-process cleanup evidence changed from
  `workers after test: 1` to `workers after test: 0`.
- Graceful shutdown: `3 passed`; reversed event order failed as expected.
- CI/deploy/DR policy file: `11 passed` after strengthening reusable CI,
  fingerprint preflight, health probe and stopped-PostgreSQL restore path.
- Independent task and holistic reviews returned APPROVE after two review fixes:
  empty fingerprint fail-closed and executable quoted health probe.

### Stage 3 — final local gate

| Check | Result |
|---|---|
| `python -m pytest tests/ -q` | `270 passed, 20 skipped in 175.48s` |
| PostgreSQL skips | 19 tests: local `DATABASE_URL`/PostgreSQL evidence absent |
| POSIX skip | 1 test: shared-volume instance lock cannot run on Windows |
| `python -m pip check` | `No broken requirements found.` |
| `node --check` | PASS: `static/js/index.js`, `auth.js`, `admin.js` |
| `bash -n` via Git-for-Windows | PASS: all 8 scripts in `scripts/` |
| Workflow YAML parse | PASS: 2 workflow files |
| Workflow/static regression tests | included in the green full suite |
| `git diff --check` | PASS |
| `pip-audit` | unavailable locally; GitHub gate only |
| Docker/Compose live DR | Docker unavailable locally; GitHub/staging gate only |

The two untracked basetemp directories contain only generated test vault/session
and SQLite artifacts. Their deletion was not authorized because it is
irreversible; they must be removed or otherwise explicitly disposed before push.

## Frozen production blockers

1. **Role percentages are not applied to allocation.**
   `app/campaign_query.py` calls `antiban_core.assign_rotation_roles`, which
   still splits profiles into fixed thirds. `split_role_counts` exists but is
   not used by that flow. This touches frozen role/human/global behavior and was
   intentionally not changed.
2. **UTC/local-day boundary mismatch remains.**
   `app/sqlite_backend.py` stores `send_log.sent_at` with SQLite
   `datetime('now')` (UTC), while `main.py::_group_sends_today` compares
   `date(sent_at)` with `_local_today()`. This touches frozen local-day semantics
   and was intentionally not changed.
3. **Production worker-pool policy is unverified.**
   `.env.example` and Compose fallback are `4`, while the release contract
   requires one campaign-owning app process and `worker_pool_size=1` for every
   production tenant. Settings/defaults were frozen, so stages 1–3 did not alter
   them. Production `.env` and persisted tenant values must be read and proved.

## External release gates

Production remains **NO-GO** until evidence exists for the exact final SHA:

- [ ] Worktree is clean; the two generated basetemp directories have an explicit disposition.
- [ ] Branch is pushed only after separate approval.
- [ ] All five GitHub CI jobs are green: `server-smoke`, `compose-config`, `dependency-audit`, `backup-restore-smoke`, `server-e2e`.
- [ ] GitHub production environment is protected and `DEPLOY_HOST_FINGERPRINT` matches the VPS host key.
- [ ] VPS `.env`, DNS/TLS, disk/CPU/RAM, backup permissions and one-app-process topology are verified without printing secrets.
- [ ] Production env and every persisted tenant setting prove `worker_pool_size=1`; no setting is changed by this audit.
- [ ] Matching-backup migration/restore rehearsal succeeds on a production-like Linux/Docker copy.
- [ ] Isolated live MAX/proxy canary is separately authorized and succeeds without changing anti-ban/human rules.
- [ ] Product owner explicitly accepts or separately authorizes fixes for both frozen role-percentage and UTC/local-day defects.
- [ ] Final manual deploy and 15-minute observation receive separate approval.

## Current decision

Stages 1–3 are locally complete, reviewed and reproducible. Production is
**NO-GO** because exact-SHA GitHub/Linux/Docker evidence, clean release hygiene,
production configuration, live canary and frozen-defect disposition are absent.
