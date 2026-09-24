# Normative Master V3 execution — Wave A

Status: `IN_PROGRESS / PARTIAL`

Baseline implementation SHA: `716516917e393834713e63b9f51e930b332bee38`

Current continuation is a worktree delta on that baseline, not yet
commit-bound. The primary `.git/index` is read-only, so the latest additions
remain unstaged; the local Git commit also requires separate explicit
authorization. Therefore the new results below are not promoted to SHA-bound
evidence.

Canonical Master source:

- path: `/mnt/c/Users/Edifi/Documents/MAXBOT_MASTER_V3_EN_2026-09-20.md`
- SHA-256: `8c7a57092be519ea5df0379abc6030124d1e099867adbc72a06174027c90392d`
- acceptance headings: `365`

This record is a local, uncommitted execution continuation. It does not
change the canonical Master, promote historical evidence, or authorize live
MAX/provider/SMS/production actions.

Current operator-shell boundary is read-only and fail-closed: `ENV_DOCKER_READY=PASS`
(`docker info` reported Docker Desktop 29.8.0; current-worktree image build and
isolated DR smoke passed), `MAX_PLATFORM_AUTHORIZATION_FILE=UNSET`,
`MAX_RECOVERY_HOLD_FILE=UNSET`, deployment target variables are `UNSET`, and the
Browser plugin is unavailable; regular Playwright 1.63.0/Chromium fallback was
used for the local rendered gate. These are current environment facts, not
application test failures.

## Wave A case disposition

Only the following cases have assertion-level evidence at this checkpoint:

| Case | Result | Evidence |
| --- | --- | --- |
| `RC01-C01` | `PASS` (source/provenance review) | Canonical Master hash/count, current SHA/worktree reconciliation, and one-task-graph rule reviewed. |
| `T00-C01` | `PASS` (bounded source comparison) | `git diff --function-context 0154884cf94d6aeccf65f5390a0f845d783c3c0e..716516917e393834713e63b9f51e930b332bee38` reviewed the changed campaign, scope, settings, SQLite and error paths; the comparison was 168 files, 15,369 insertions and 746 deletions. |
| `T00-C02` | `PASS` | A detached temporary worktree at `716516917e393834713e63b9f51e930b332bee38` was clean; primary status and staged-index fingerprints were unchanged before/after (`PASS`). |
| `T00-C03` | `PASS` (recording disposition) | `MAX_PLATFORM_AUTHORIZATION_FILE=UNSET`; the baseline explicitly retains SMS and production evidence as `NOT RUN`, with no live action inferred. |
| `T00-C04` | `PASS` (read-only baseline) | Read-only queries of `data/app.db` and `data/global/app.db` retained actual settings: `delay_min_sec=45`, `delay_max_sec=15`, `daily_limit_min=5`, `daily_limit_max=10`, `max_msgs_per_profile_day=10`; no proposed values were written. |
| `T01-C01..C03` | `PASS` | `tests/test_audit_harness.py`, `tests/test_external_action_boundaries.py`, tenant fixtures; 49-case Wave A rerun. |
| `T02-C01..C02` | `PASS` | `tests/test_data_scope_v2.py`, `tests/test_tenant_isolation_sqlite.py`, `tests/test_phase3_tenant_scope.py`; 49-case Wave A rerun. |
| `T02-C03` | `PASS` | `tests/test_data_scope_v2.py::test_ambiguous_legacy_scope_is_reported_without_distribution`; the dry-run fixture remains blocked and the legacy file is retained. |
| `AUD20-A23-C01` | `PASS` (isolated fake MAX local-data scope) | `tests/test_data_scope_v2.py::test_max_data_scopes_keep_api_worker_cache_vault_backup_and_cleanup_separate` exercises API log/backup, campaign worker runtime, tenant rate-limit cache, per-tenant vault/session encryption and quarantine cleanup for tenants `1` and `2` with the same local profile ID; snapshots and logs remain scope-local. No production data or provider action is involved. |
| `T03-C01..C04` | `PASS` | `tests/test_error_taxonomy_v2.py`; 49-case Wave A rerun. |
| `AUD20-A05-C01` | `PASS` (isolated fake adapter/operation scope) | `test_adapter_failure_matrix_preserves_conservative_operation_state` covers revoked session, confirmed destination rejection, confirmed wait and in-flight transport ambiguity; the auxiliary MAX gateway fixtures persist wait/ban restrictions before rethrow. Pre-send cases create no send, wait preserves the cooldown, revoked session marks `needs_reauth`, and ambiguity remains `unknown` and non-retryable. |
| `COMP-R01-C01` | `PASS` (isolated fake classification scope) | `tests/test_error_taxonomy_v2.py` keeps proxy authentication/connection failures separate from a confirmed MAX ban, while the A05 operation matrix keeps the MAX-side outcome conservative. No proxy or MAX network was used. |
| `RC16-C01` | `PASS` (local loopback browser scope) | `reconcile and wait actions never trigger mutation or auth retries` verifies `COMMAND_STATE_UNKNOWN` reads only the bounded send log, while `MAX_RATE_LIMIT` and `API_RATE_LIMIT` show status; no campaign mutation or auth-code endpoint is called. The browser fixture is loopback-only. |

The following Wave A cases remain `NOT_RUN` and are not inferred from green
supplemental tests:

- `UI-C03` and all 66 `ERR-*-C01` cases have the separate `PARTIAL` fixture
  dispositions below: every catalogue code is rendered visibly on the
  cabinet/admin/impersonation fixtures and every normalized action token is
  invoked through local review/authentication paths, while auxiliary
  WebSocket/cache/export consumers, external replay and human visual review
  remain open.

The restricted-sandbox hang in `tests/test_live_mutation_safety.py` was
classified as an environment boundary. The same bounded test completed
outside that restriction with `16 passed`; it is not converted into a case
failure.

## Exact-SHA evidence executed

All commands below ran against the implementation SHA above, with fake or
fixture-only external boundaries:

| Scope | Result |
| --- | --- |
| Wave A focused SQLite suite | `49 passed` in `2.66s` |
| Full SQLite suite | `499 passed, 19 skipped` in `17.98s`; skips are PostgreSQL modules |
| PostgreSQL module suite | `19 passed` |
| PostgreSQL server E2E | `4 passed` |
| Existing T04–T11 task-bound suites | `95 passed` |
| Existing T12–T14 task-bound suites | `73 passed` |
| Required `T15 -> T33 -> T14` focused sequence | `42 passed` |
| Extended normative task-contract matrix (T04–T30 consumers, fake/fixture-only) | `197 passed, 3 skipped` in `8.20s` |
| Loopback Playwright fallback, `390/768/1440` | `21 passed`; Browser plugin unavailable |
| compileall, Node syntax, shell syntax, JSON, `git diff --check` | `PASS` |
| `pip check` | `PASS` |
| `pip-audit -r requirements.lock` | `PASS`, no known vulnerabilities |
| `pip-audit -r requirements-server.lock` | `PASS`, no known vulnerabilities |
| Docker Compose config with synthetic values | `PASS` |
| Isolated Docker build/backup/restore/recovery-hold smoke | `PASS`; health reported `db_ok=true`, `max_external_actions=held`, `recovery_hold=true` |

## Continuation checks (not yet SHA-bound)

The following checks ran against the current worktree delta and remain
`PARTIAL` until the same source/test snapshot receives an explicitly
authorized commit:

| Scope | Result |
| --- | --- |
| Structured error catalogue Python coverage | `15 passed`; all 66 catalogue codes have documented safe actions; retry deadlines are bounded and timezone-aware |
| Structured error catalogue browser contour | `8 passed` on `390x844`; cabinet, admin and impersonation render all 66 codes with visible alerts, unknown-code/stale-dashboard fixtures pass, every normalized action is invoked, and the reconcile/wait matrix proves no mutation or auth retry through local review/status paths |
| Current T01–T03 regression contour | `41 passed` in `2.55s` with a loopback-only fixture `REDIS_URL`; no Redis connection was made |
| Full SQLite suite after the delta (earlier writable rerun) | `617 passed, 19 skipped` in `22.73s` through `timeout 120s .venv/bin/pytest -q`; skips are PostgreSQL modules |
| Current bounded non-`TestClient` regression contour | `580 passed, 5 skipped` in `18.30s` with a test-only joinable-thread shim; 11 known Starlette `TestClient`-dependent modules were excluded because the installed portal does not return |
| Earlier full regression with runner compatibility | `633 passed, 19 skipped` in `23.17s` through `MAXBOT_TESTCLIENT_UVLOOP=1 MAXBOT_TEST_THREAD_SHIM=1 timeout 120s .venv/bin/pytest -q`; both hooks are opt-in and test-only for this restricted runner; no application or production dependency is replaced |
| Post-T07/A05/A43/RC16/T11/T13 full regression with runner compatibility | `645 passed, 19 skipped` in `26.20s` through the same opt-in test-only hooks; the auth watcher/session, destination revision/API confirmation, post-boundary flood-wait fence and auxiliary restriction fixtures plus earlier normative fixtures are green and no application or production dependency is replaced |
| Latest current-worktree full regression after command receipt, read-only receipt lookup, auxiliary worker-claim, T07 A15/A17, RC10 policy retry, AUD20-E08 SDK/content contract, T11 manual-Test destination fencing, error-consumer redaction, T26-C01..C05, missing-table receipt, T27 OTP focus and T26 WebSocket log-redaction coverage | `684 passed, 19 skipped` in `29.55s` using the same opt-in test-only hooks; PostgreSQL cases were not included in this invocation |
| Post-A40 full regression recheck | `633 passed, 19 skipped` in `23.68s` through the same opt-in test-only runner hooks; immediate post-recovery JWT issuance/validation is covered by the final A40 runtime smoke below |
| Post-structured-error UI source full regression recheck | `633 passed, 19 skipped` in `22.47s` through the same opt-in test-only runner hooks; this recheck followed the visible role-surface/action-contour fix and makes no production event-loop claim |
| Dedicated PostgreSQL module and server E2E continuation | Current dirty candidate: `19 passed` in `10.64s` plus `4 passed` in `4.89s` against the pinned PostgreSQL 16 image on a disposable tmpfs-only container; 62 Starlette cookie deprecation warnings total, no test failures; container auto-removed after the run |
| Current dependency vulnerability audit | `PASS`; `pip-audit --no-deps --disable-pip` found no known vulnerabilities in both `requirements.lock` and `requirements-server.lock`; image-level scanner and history review remain separate |
| Live-mutation safety fixture suite | `17 passed` outside the sandbox restriction; the restricted run remains an environment hang, not an application PASS/FAIL |
| Full loopback Playwright after the delta | Earlier runs: `78` scheduled / `44 passed` / `34` skips, then `87` / `47` / `40`. Latest after expanded error-state screenshot coverage: `87 scheduled, 57 passed, 30 expected viewport-bound skips` across `390x844`/`768x1024`/`1440x1000`; includes stable Start receipt recovery, ambiguous Test no-repeat after reload, OTP focus and keyboard-height checks, and user/admin/impersonation rendering of all 66 error codes at all three viewports. No unexpected external request, console/page error, failed request or HTTP error. Browser plugin unavailable; full manual visual review and real mobile keyboard remain open |
| Dynamic T20 executor responsiveness fixture | `PASS` (local fixture scope); `9 passed` in `0.63s` with a test-only joinable-thread shim exercising status/backup, campaign Stop/Pause coordinator transactions and persistence, admin password-registration offload, a live loop ticker and 100 synthetic WebSocket/auth cycles under `tracemalloc`; source still asserts production `asyncio.to_thread` boundaries, but no production p95/SLO claim |
| Test-mode shutdown lifecycle | `5 passed`; bounded worker/login/lease shutdown and inline test-mode reseal complete; the installed runner's `TestClient`/`asyncio.to_thread` portal boundary remains external to application assertions |
| T11/T13 association, destination, consent and restriction continuation | `62 passed in 7.87s`; automatic single-membership migration, explicit work-group selection, deletion fencing, destination invalidation, old-route preservation with explicit new-destination confirmation API/UI and stale revision fencing, selected-group unlink cancellation, membership review, auxiliary wait/ban selection fencing, revoked-consent queued-slot cancellation and global identity-claim fixtures are local evidence only |
| Static checks after the delta | `PASS`; compileall, Node syntax, shell syntax, `pip check` and `git diff --check` |
| Current-worktree Docker build and isolated DR smoke | Earlier isolated DR smoke: `PASS`; PostgreSQL/Redis/app health, backup/restore of PostgreSQL and `max_server_data`, and `verify_deploy.sh` passed with `max_external_actions=held` and `recovery_hold=true`; temporary containers/volumes were removed |
| Latest app image build after command-receipt source changes | `PASS` (local build scope), `docker compose ... build --pull=false app` with synthetic interpolation values; BuildKit manifest list `sha256:432a0de5a5f67883ff030f8af1fcf1c13eb7303d460db38bbfe9c1ce16ef1089`; no service startup/push/deploy/provider |
| Latest app image build after receipt regressions, T27 UI fix and local T30 checks | `PASS` (local build scope), current source rebuilt via `docker compose --env-file /dev/null build --pull=false app` with synthetic interpolation values; BuildKit manifest list `sha256:1570acf6eec75061cc02a7884ec87406fe17200680d65198b6a112f2b917a15e`; no service startup, image publication, deploy or provider action |
| Current post-boundary-flood Docker rebuild | `PASS` (local build scope); the current source rebuilt with synthetic placeholders as BuildKit manifest list `sha256:2e0ac8d899786d22cc1290624c319c34e933489023b653008df493f4dbe6466c`; no service was started, published or connected to a provider |
| Current readiness UI image and Compose smoke | `PASS` (local stack scope); manifest `sha256:7f69ebfd52eb393a0c4e3da7fc4ec396a82fa1b05e1d48dfd8c47e0aceaaec60` started with PostgreSQL/Redis/app healthy and health returned `ok=true`, `db_ok=true`, `server_mode=true`; synthetic JWT met the fail-closed length contract, and exact temporary resources were removed |
| Fresh server-mode Compose smoke | `PASS` (local stack scope); app + PostgreSQL + Redis started from the current image, public and authorized health passed (`db_ok=true`, `redis_ok=true`, `server_mode=true`); the fresh non-restore control volume had no recovery hold, while the platform authorization file remained unset and no provider action was attempted |
| Post-runtime-fix Compose smoke | `PASS` (local stack scope); the prior runtime image manifest was `sha256:3646a3f048366c1094c248d4d5a64faa4295bc06980a90cc630761af5969cfef`; app/PostgreSQL/Redis reached healthy, authorized health returned `ok=true`, `db_ok=true`, `server_mode=true`, `max_external_actions=authorized`, `recovery_hold=false`; this remains a local stack smoke and not production PostgreSQL/provider proof |
| Current-worktree loopback browser matrix | `PASS` (local rendered scope); regular Playwright fallback, Chromium, fresh `87` scheduled across `390x844`/`768x1024`/`1440x1000`, `57 passed`, `30` expected viewport-bound skips, no diagnostics violations or external requests; includes Start/ambiguous-Test receipt recovery, OTP focus/keyboard-height, and error catalogue screenshot states at all viewports |

These worktree results do not change the case dispositions above or close any
Master case by aggregation.

## Local assertion-level continuation dispositions

These are deliberately `PARTIAL`, not `PASS`: they prove the bounded local
fixture assertions listed below but do not prove every permitted action or any
live boundary.

| Case set | Result | Evidence and remaining boundary |
| --- | --- | --- |
| `ERR-*-C01` (all 66) | `PARTIAL` | `tests/browser/error_catalogue.spec.js` repeats every code on visible cabinet, admin and impersonation surfaces, preserves safe message/source/stage/action metadata, drops unknown preservation metadata, checks no raw sentinel, and invokes every normalized action token without provider traffic. Synthetic-secret regressions now prove unknown-send and terminal rejected-send paths persist only catalogue safe messages in the operation ledger, send log, profile last_error, ban-stop reason and application log; retry decision/state and confirmed ban stopping remain intact. A per-row bulk profile-import failure returns a safe structured `UNCLASSIFIED` envelope; dashboard/server-log storage failures return safe structured errors without exception text in logs; legacy `send_log.error` values are redacted and surfaced with safe code/action metadata; credential-bearing server log lines are hidden on stdout, persistence, `/api/log` and `/api/status`, including legacy rows; and legacy profile errors are normalized before dashboard, group-profile and profile-list/detail API projections. Other API/WebSocket/cache/export consumers and external replay remain open. |
| `UI-C03` | `PARTIAL` | Fresh regular Playwright fallback ran `87` scheduled tests across `390x844`, `768x1024` and `1440x1000`: `57 passed`, `30` expected viewport-bound skips. It includes safe error rendering/actions for all 66 catalogue codes on user/admin/impersonation surfaces, unknown-code fallback, stale-dashboard suppression, keyboard/reflow, two-tab transport, auth/recovery/error states, RC16 reconcile/wait, bounded CSV import, stable command receipt recovery, and OTP controls/focus at a keyboard-reduced viewport. Diagnostics found no unexpected external requests, console/page errors, failed requests or HTTP errors. Human 200% zoom/contrast/full visual review, real mobile keyboard and auxiliary non-renderer consumers remain open; this is local Playwright evidence, not independent/manual browser acceptance. |

## Wave B local continuation (`T04`–`T06`)

These rows are case-level local evidence only; external MAX/provider behavior,
the standalone migration dry-run, and the full consumer obligations remain
separate dispositions.

| Case set | Result | Evidence and remaining boundary |
| --- | --- | --- |
| `T04-C01` | `PASS` (local fixture scope) | `legacy_route_migration_report` is read-only and returns `REVIEW_REQUIRED` for a populated legacy `profile.proxy` without exposing it, probing, login or creating an assignment; explicit production migration remains unauthorized. |
| `T04-C02`, `T04-C03`, `T04-C04`, `T04-C05`, `T04-C06`, `T04-C07` | `PASS` (local fixture scope) | `tests/test_proxy_resolution_v2.py`, `tests/test_connections_api_v2.py`, `tests/test_group_proxy_server.py`, `tests/test_admin_tenant_settings.py`; `32 passed` current worktree contour, including stable login/send assignment, 30-account catalog growth, fixed sender pool of one, explicit selection, revision and disabled-route fail-closed behavior. |
| `T05-C01..C04` | `PASS` (local fixture scope) | `tests/test_proxy_probe_v2.py`; fragmented CONNECT, 407/EOF/oversize responses, strict URL parsing, IPv6/escaped credentials, TLS success and `max_handshake=NOT_CHECKED` with `otp_calls=0`. |
| `T06-C01`, `T06-C03`, `T06-C04` | `PASS` (local SDK/client scope) | `tests/test_pymax_241_contract.py`, `tests/test_max_client_version.py`, `tests/test_client_lifecycle_v2.py`; installed SDK signatures, fixed TLS/target policy, identity preservation and close/outcome behavior. |
| `T06-C02` | `PASS` (local fixture scope) | `tests/test_max_gateway.py` now drives a `session_required` send failure and asserts exactly one adapter send with no OTP/relogin; saved-session/no-fresh-retry fixtures also pass. Live revoked-session behavior remains unrun. |
| `AUD20-A39-C01` | `PARTIAL` | Current-worktree PyMax 2.4.1 signature/runtime/session follow-up is `16 passed`, including installed `send_message`/`add_reaction` public contract checks. The retained-version 2.4.0 comparison and fresh security evidence remain open; no historic CVE scan is promoted to current evidence. |
| `AUD20-E08-C01` | `PASS` (isolated SDK/fake-adapter local scope) | The installed PyMax 2.4.1 public contracts are exercised by `tests/test_pymax_241_contract.py`; `Client.add_reaction` is async with `(chat_id, message_id, reaction)`, and `GuardedMaxGateway` forwards the exact Unicode reaction and IDs only when `ADD_REACTION` is explicitly authorized (`tests/test_max_gateway.py`). Existing A43 fixture coverage sends exact Unicode, quoted separators and literal JSON unchanged to the fake gateway. Message-library parsing is bounded at 5 MiB/10,000 items, and the upload route rejects over-limit input before publication (`tests/test_message_versions_v2.py`, `tests/test_routes_panel.py`). No provider-side text/service limit is inferred and no live provider action occurred. |

## Wave C local continuation (`T07`–`T11`)

The following local contours were rerun against the current worktree continuation. They
do not imply that the missing external or consumer assertions were executed.

| Case set | Result | Evidence and remaining boundary |
| --- | --- | --- |
| `T07-C01` | `PASS` (local fake/loopback fixture scope) | A profile already in `needs_reauth` starts a distinct attempt, reaches `waiting_code` without the previous error terminating the watcher, and completes the browser fixture flow `needs_reauth → connecting → waiting_sms → active`; the focused loopback case passed on `390x844`. Production/provider behavior remains separate. |
| `T07-C02` | `PASS` (local fake session scope) | Saved-session timeout preserves the encrypted session byte-for-byte with no reauth backup; the explicit fresh path stages/restores the old session on failure; send paths do not request SMS. The full adapter fault matrix and live lifecycle remain separate. |
| `T07-C03..C05`, `COMP-R03-C01` | `PASS` (local fixture scope) | `app/services/auth_attempts.py`, canonical `/auth-attempts` routes, route-level cloud-password fixtures and `tests/test_auth_attempts_v2.py` / `tests/test_profile_auth_endpoints_v2.py` cover scope/attempt/revision/stage guards, 404/409/410 classes, one-request idempotency, no duplicate secret queueing, persisted restart interruption and a 90-second connection deadline inside a 600-second attempt. |
| `AUD20-A15-C01` | `PASS` (isolated fake MAX/local encrypted-session scope) | `test_ordinary_login_faults_reseal_same_saved_session_without_sms_or_fresh_login` injects timeout, proxy refusal, TLS handshake and local SQLite identity-read failures through the real decrypt/client/reseal boundary; `test_ordinary_login_tolerates_benign_tls_disconnect_and_reseals_session` covers benign close-notify. All preserve token, phone, device/instance and user-agent identity after decrypting the resealed session; no reauth staging occurs and the SMS queue remains empty. No live lifecycle/provider assertion is inferred. |
| `AUD20-A17-C01` | `PASS` (local auth-attempt/API/SQLite scope) | `test_expired_attempt_input_cannot_enter_new_stage_and_password_receipt_is_safe` lets the old code-input stage expire, advances a new attempt to password input, rejects the stale code with 410 without queueing it, repeats the same password command ID with one queue effect, preserves leading/trailing password spaces and confirms OTP/password values are absent from persisted attempt metadata. Existing attempt tests additionally cover duplicate code ID and wrong-stage/revision rejection. No provider traffic occurred. |
| `T08-C01..C03` | `PASS` (local integrated fixture scope) | `ClientManager` is now the live `_with_client` owner for login/send leases; cancellation awaits bounded close, session deletion drains before `rmtree`, shutdown cancels/awaits login tasks and leases, and `tests/test_client_lifecycle_v2.py`, `tests/test_session_send_no_otp.py`, `tests/test_profile_auth_endpoints_v2.py` cover serialization, accepted-outcome preservation, cancellation and idempotent shutdown. |
| `T08-C04` | `PASS` (bounded Windows OS primitive + route failure-injection scope) | A Windows Python 3.14.1 probe held a quarantine file without `FILE_SHARE_DELETE`: `shutil.rmtree(ignore_errors=True)` falsely returned success while the file remained; strict `shutil.rmtree` raised `PermissionError` and preserved it. Linux route tests verify 409 and preserved live data before DB deletion, and 409 plus retained quarantine after DB deletion. Focused deletion module: `4 passed`; full SQLite suite: `693 passed, 19 skipped`. This is not a full native Windows application/pytest run, which remains unavailable. |
| `T09-C01..C04` | `PASS` (local/review scope) | `tests/test_vault_migration_v2.py`, vault isolation tests and the security review cover semantic reseal, corrupt/wrong-key holds, preserved originals and the explicit limitation that a colocated machine key does not protect a stolen full directory. |
| `T10-C01`, `T10-C03` | `PASS` (local fixture scope) | Online SQLite backup integrity, private `.app_key` handling, archive checksums/permissions and no-CI-secret policy are covered by `tests/test_backup_consistency_v2.py` and `tests/test_backup_scripts.py`. |
| `T10-C02` | `PASS` (local failure-injected Docker scope) | An isolated restore with an intentionally invalid `pg.dump` returned non-zero, restored the old data volume, retained `recovery-hold.json` and left the staged replacement in `.outgoing-restore`; temporary resources were removed. Production PostgreSQL remains separate. |
| `T10-C04` | `PASS` (local MAX_DATA fixture scope) | A current-worktree server-mode fixture with an arbitrary `MAX_DATA` root created scheduled backups for global and tenants `11`/`22` and did not use `ROOT/data`; live scheduler timing and production volume remain separate. |
| `AUD20-A34-C01` | `PASS` (local SQLite WAL fixture scope) | An old reader held a WAL snapshot while a writer committed new data; the online backup returned an integrity-checked snapshot containing the committed row. No stale file copy was used. |
| `AUD20-A35-C01` | `PASS` (local recovery-hold fixture scope) | With persisted `auto_run=1` and a nonzero accepted counter, auto-resume made no worker call before or after reloading the application modules; the counter stayed unchanged and the external recovery hold remained present. No provider action was used. |
| `AUD20-A37-C01` | `PASS` (local Docker rollback topology scope) | An isolated invalid-PG-restore fixture contained global and two tenant scope markers; rollback restored all old scopes, retained the staged replacement and recovery hold, and performed no automated send. Production PostgreSQL remains separate. |
| `T11-C01`, `T11-C02` | `PASS` (local fixture scope) | `test_changing_group_link_invalidates_cached_destination` clears the old chat identity before a new link can be used; selected-group unlink preserves the second association/session, marks the scope unselected and cancels only queued work pinned to the removed association. |
| `T11-C03`, `T11-C05`, `T11-C08` | `PASS` (local fixture scope) | `test_deleting_profile_rejects_new_client_acquisition` and `test_login_is_fenced_while_profile_runtime_is_deleting` reject new runtime work with 409; non-selected work groups stop before `_login_max`; `test_membership_review_stops_before_send_without_retrying` records `MEMBERSHIP_REVIEW_REQUIRED` without retry or send. |
| `T11-C06` | `PASS` (local worker fixture scope) | `test_revoked_consent_cancels_queued_slots_without_claiming_or_sending` marks only queued slots `cancelled` with `CONSENT_REVOKED`; the next claim sees no eligible work. |
| `T11-C04` | `PASS` (local history fixture scope) | `test_send_history_keeps_archived_group_rows` keeps a sent row joined to an inactive group in the authorized send-history projection; permission enforcement and tenant-wide history consumers remain separate. |
| `T11-C07`, `AUD20-A11-C01` | `PASS` (local migration fixture scope) | Schema upgrade migrates exactly one enabled legacy membership, leaves multiple memberships unselected, exposes explicit `PUT /api/profiles/{id}/automation-scope`, rejects unlinked choices, keeps dashboard `primary_group_id` empty until explicit selection, and preserves session material; production migration execution remains unrun. |
| `T11-C09`, `AUD20-A18-C01`, `RC09-C01` | `PARTIAL` | A global identity-claim registry now fails closed without exposing the other tenant; the local login conflict path keeps the profile `needs_reauth` and preserves the existing claim. The integrated destination continuation keeps old accepted route history unchanged, blocks a changed queued route before SDK work, exposes an explicit owner confirmation API/UI bound to the current revision, and permits the new chat only after verification. A newly reproduced manual-Test race is now fenced: both changing the link and confirming a replacement destination return 409 while persisted campaign control is `testing`, leaving the old verified destination untouched. Admin-review integration, production legacy claims and the complete concurrent destination-revision race matrix remain open. |

These results are implementation evidence, not automatic closure of the 365
Master cases. Normative completion still requires the remaining case-level
assertions, review/authorization dispositions, and exact traceability for
every `T00..T33`, `AUD20`, `COMP`, `RC`, `UI` and `ERR` case.

## Wave D local continuation (`T12`–`T15`, `T33`, `T14`)

The dependency order `T15 -> T33 -> T14` was exercised on the current
source. These are local fake-MAX/SQLite assertions; they do not establish a
production send, provider acknowledgement, or full closure of the 365 cases.

| Case set | Result | Evidence and remaining boundary |
| --- | --- | --- |
| `T12-C01..C07`, `AUD20-A01..A04`, `AUD20-A07`, `RC03-C01`, `AUD20-E06-C01` | `PASS` (local fixture scope) | Operation-ledger, coordinator and campaign-operation tests cover durable claim/in-flight/unknown, no replay after ambiguity including a post-boundary flood wait, persisted retry-after, pre-send identity retention, idempotent finalization, sender ownership and flood-like post-ACK cleanup errors. Subprocess crash matrix and provider boundary remain unrun. |
| `T13-C01..C04`, `T13-C06`, `T13-C11`, `AUD20-A06-C01`, `COMP-R04-C01`, `COMP-R06-C01` | `PASS` (local fixture scope) | `tests/test_pacing_policy_v2.py` and campaign-operation fixtures cover role targets, read-only snapshots, tenant sanction scope, full server deadline, floor-after-jitter, frozen UTC+3 budget date and review-required unclear waits. |
| `T13-C05`, `AUD20-A29-C01` | `PASS` (local integrated SQLite scope) | `tests/test_global_pacing_settings.py` covers one atomic allowlist policy revision per scope, durable desired/applied state, no secret/`auto_run` fan-out, independent tenant transactions and a controlled partial failure with durable `policy_apply_results`; cross-database atomicity is explicitly not claimed. |
| `AUD20-A13-C01` | `PASS` (local fixture scope) | `tests/test_role_rotation.py::test_late_member_does_not_reshuffle_pinned_roles` proves a midday late arrival receives `skip` while existing role/day-order snapshots remain unchanged. |
| `COMP-R07-C01` | `PASS` (local fixture scope) | `tests/test_role_rotation.py::test_role_rotation_is_independent_from_send_window_switch` proves disabling the window/pacing switch does not disable the fixed three-day role policy. |
| `T13-C07`, `COMP-R05-C01` | `PASS` (local fake/controller/worker scope) | `test_max_gateway_wires_auxiliary_restriction_handler` verifies the authorized fake `mark_read` path awaits the controller and rethrows; campaign-operation fixtures persist full cooldown/ban state; `test_auxiliary_wait_prevents_worker_claiming_the_following_send` then exercises the real worker claim path and proves no send-job is claimable during the persisted wait. No production MAX client/provider action was used. |
| `RC10-C01` | `PASS` (isolated multi-tenant SQLite fixture scope) | `test_partial_policy_retry_and_stop_start_preserve_v1_plans_and_revocation` exercises a partially failed global V2 fan-out over V1 plans, verifies each scope's actual applied revision, retries the same desired revision, and performs Stop/Start in both tenants. Re-materialization with a higher quota and V2 library leaves each current plan's ID/target/V1 version unchanged; consent-revoked slots remain cancelled after Stop/Start. This does not prove concurrent production fan-out behavior. |
| `T13-C10` | `PASS` (local fixture scope) | `test_duplicate_group_records_share_one_configured_profile_cap` checks two duplicate destination records against the same configured profile limit: both remain eligible below five and both are blocked at five, with no invented cap of three. |
| `T13-C08` | `PASS` (local integrated fixture scope) | `test_materialization_keeps_production_sampled_bounds_and_auto_run` runs the actual daily-plan consumer with `daily_limit_min=5`, `daily_limit_max=10`, warmup disabled and `auto_run=1`; the sampled target stays in the configured range and auto-run remains enabled. |
| `T13-C09`, `RC05-C01` | `PASS` (local policy fixture scope) | `test_server_deadline_across_business_midnight_still_blocks_until_expiry` keeps a confirmed provider deadline through the UTC+3 business-date transition and allows continuation only after expiry; live worker/recovery timing remains unrun. |
| `T15-C01` | `PASS` (local integrated fixture scope) | `tests/test_daily_plan_integration_v2.py::test_published_v2_waits_for_next_business_day` proves a materialized V1 remains pinned today while the next business day uses published V2. |
| `T15-C02..C06` | `PASS` (local fixture scope) | `test_legacy_message_pool_random_norepeat_exhausts_one_tenant_deck`, `test_library_items_are_reused_for_each_account_pass_without_mutation`, `test_pre_network_retry_reuses_operation_identity_and_text`, `test_current_endpoint_keeps_five_items_after_two_complete_account_passes` and `test_auto_run_next_day_materializes_existing_library_without_reimport` cover one-deck exhaustion, independent passes, frozen retry text, current-version retention and restart/next-day reuse. Live/provider/browser boundaries remain separate. |
| `AUD20-A30-C01` | `PASS` (local fail-closed fixture scope) | `test_corrupt_legacy_bag_is_not_rebuilt_or_replayed` and `test_publication_failure_keeps_pool_version_and_queue_checkpoint` keep malformed bags, tenant-reset failures and immutable-publication failures from silently replanning, replaying or reporting cross-tenant partial success; exhaustion, next-day reuse and concurrent manual reservation fixtures also pass. Live/provider boundaries remain separate. |
| `AUD20-A43-C01` | `PASS` (local isolated fake scope) | `test_a43_message_import_preview_publish_and_retry_keep_frozen_text` joins UTF-8/BOM TXT import, route preview, immutable publication, daily-slot selection, a replacement library publication, proven pre-send requeue and a two-attempt fake send; the same slot and exact Unicode/quoted-separator/literal-JSON/duplicate text reach the fake gateway unchanged. Existing preview-limit and parser/browser fixtures add the byte/item, unterminated-quote and 2000-row bounds. No external MAX/provider action occurred. |
| `RC11-C01` | `PASS` (local fixture scope) | Empty/short pools wait or reuse the immutable library without depletion; waiting-pool fill is one-shot, literal JSON survives rendering, and pre-network retry/restart fixtures retain the same selected text/account. Live/provider boundaries remain separate. |
| `T33-C01..C15`, `T33-C19`, `T33-C24` | `PASS` (local fixture scope) | Daily-plan selection/persistence/worker/integration fixtures cover independent targets, quiet/skip, queued-slot claim, occupied unknown, bounded pre-send retry, proxy-preflight plan retention, same-day Stop/Start retention, 100 read-only GETs without RNG/writes, concurrent single materialization, pass selection, empty/waiting pool and account-owned scheduling. |
| `T33-C16..C18` | `PASS` (local integrated fixture scope) | `test_published_v2_waits_for_next_business_day` reopens the SQLite database before publishing V2 and keeps today’s V1; auto-resume accepts a current immutable library without legacy `message_pool`, creates the next-day plan without TXT reimport, and blocks auto-run for `auto_run=0`, banned and revoked-consent profiles while retaining the library. No live MAX action is implied. |
| `T33-C20` | `PASS` (local fixture scope) | `test_stop_start_same_day_keeps_remaining_slots` changes the requested work-group after two accepted sends and retains the original plan, account and remaining slots. |
| `T33-C25` | `PASS` (local fixture scope) | `test_unauthorized_group_assignment_stays_queued_before_sdk_boundary` supplies a non-authorized eligible assignment; the pinned slot remains queued for its original group and no SDK boundary is reached. |
| `T33-C26` | `PASS` (local readiness fixture scope) | `test_campaign_preview_reports_window_shortfall_without_mutation` computes minimum one-sender capacity from the configured window and mandatory delay, reports `daily_plan_window_shortfall`, and leaves the plan/limits unchanged; external timing and provider failures remain outside the fixture. |
| `T33-C23` | `PASS` (local synthetic topology scope) | `test_synthetic_topologies_preserve_group_proxy_plan_ownership` compares one group/50 proxies with two groups of 30/5 proxies, retaining account→group→proxy and account-owned slots with one sender. |
| `AUD20-A10-C01` | `PASS` (local integrated fixture scope) | `test_two_account_plans_keep_selection_and_library_through_restart` preserves exact independent selections, accepted state, work groups and reusable library version across repeated materialization and restart. |
| `AUD20-A12-C01` | `PASS` (local integrated fixture scope) | `test_yesterday_counters_require_explicit_plan_and_survive_reset_restart` proves a read does not create a plan; explicit materialization survives counter reset and database restart with the same slots. |
| `RC04-C01` | `PASS` (local integrated fixture scope) | `test_manual_test_cannot_add_sixth_send_after_allocated_plan` finishes `accepted=3/unknown=1/queued=1` as four accepted plus one unknown and rejects a further manual test before SDK/preflight. |
| `T33-C21` | `PASS` (local migration fixture scope) | `test_verified_legacy_accepted_count_allows_only_remaining_budget` and `test_legacy_verified_accepted_sends_reduce_first_daily_plan` verify that a reconciled current-day accepted count is subtracted from the first plan target; production data migration remains separately unrun. |
| `T33-C22` | `PASS` (local fail-closed migration fixture scope) | `test_ambiguous_legacy_history_requires_review_without_fresh_budget`, `test_legacy_ambiguous_history_blocks_fresh_daily_plan` and `test_campaign_preview_and_start_block_ambiguous_legacy_budget` expose `MIGRATION_REVIEW_REQUIRED` and prevent a fresh plan/worker; production migration review remains separately unauthorized. |
| `T14-C01`, `T14-C03`, `T14-C04` | `PASS` (local fixture scope) | Preview read-only behavior, persisted Test/Start/Stop fencing, receipt replay without a second provider call, idempotent Stop and subscription/ban blocking pass in `tests/test_campaign_commands_v2.py` and `tests/test_campaign_modules.py`. |
| `T14-C02` | `PASS` (local API fixture scope) | `POST /api/campaign/preview` computes a read-only SHA-256 readiness revision; `campaign_start` accepts an unchanged revision and returns `409 PREVIEW_STALE` after a group change. The fixture asserts no plan/role/queue mutation; browser and live-provider boundaries remain separate. |
| `T14-C05` | `PASS` (local integrated fixture scope) | `test_repeated_start_creates_one_plan_per_profile_not_a_pool_broadcast` repeats the same Start request, observes one worker invocation, and asserts two independent plans with targets 5 and 7. |
| `T14-C06` | `PASS` (local fixture scope) | `test_auto_run_zero_does_not_resume_existing_library_on_next_day` keeps the immutable library available but does not start a worker or materialize a new plan when `auto_run=0`. |
| `AUD20-A08-C01` | `PASS` (local async/SQLite scope) | `test_concurrent_manual_tests_reserve_one_remaining_daily_slot` plus `test_concurrent_legacy_manual_operations_share_one_reservation` prove one local daily-slot/legacy-operation reservation; `test_manual_test_blocks_start_and_stop_fences_completion` proves the persisted Test/Start/Stop fence; `test_campaign_test_waits_for_message_pool_publication_lock` and the upload lock fixture prove Test and immutable-library publication share one short lock before selection/materialization; repeated Test receipt replay makes no second provider call. Live multi-process/provider behavior remains outside this local case. |
| `AUD20-A09-C01` | `PASS` (local fixture scope) | `test_campaign_start_is_fenced_when_stop_wins_during_preflight` proves persisted Stop wins before worker creation, no old generation starts, and the Stop command is idempotently readable after the pending preflight. |
| `RC06-C01`, `UI-C07` | `PARTIAL` | Persisted Stop/control-generation fencing rejects a stale successful Test result after Stop wins; the dashboard readiness preview remains read-only and explicit Start is bound to its revision. This continuation adds stable per-command request IDs, sessionStorage recovery and a tenant-scoped read-only receipt endpoint for Start/Stop/Pause/Test; the GET performs only a scoped receipt `SELECT` and does not initialize/write control state, including when the receipt table is absent. A follow-up closes an HTTP 409 ambiguity: the saved ID is released only after authoritative `not_found` or terminal receipt; `unknown`/pending receipts remain locked against duplicate Test sends. Focused browser receipt recovery (`3 passed`), campaign/tenant Python contour (`17 passed`) and latest full suite (`684 passed, 19 skipped`) pass. Latest full loopback Playwright matrix: `57 passed, 30 expected viewport-bound skips` from `87` scheduled. Full UI stale/loading/permission/stop-pending and visual/manual acceptance, remaining Master traceability, and live/provider acceptance remain open. |

The combined dependency-ordered local contour was `84 passed in 4.77s`.
The latest T15/T33/T14 continuation rerun, including the immutable-library,
queue-integrity, rendering, publication-rollback and bounded-import fixtures,
was `93 passed in 5.60s`. The vanilla restricted runner still hangs in the
installed `anyio`/Starlette `TestClient` portal and its default
`asyncio.to_thread` result path, but the current full-tree compatibility run
below reproduces all non-PostgreSQL cases without excluding the affected
modules; the compatibility hooks remain test-only and do not establish
production event-loop evidence.

The subsequent uncommitted delta rerun was split to avoid that known portal:
T11/identity/dashboard/lifecycle `44 passed, 3 deselected`,
campaign/daily/operation `81 passed`, max-gateway/operation/flood `29 passed`,
the pacing/library/import/error/UI contour `45 passed`, and campaign/ban/worker
regressions `25 passed`; these are current-worktree local results, not new
SHA-bound release evidence.

The follow-up Test/Start/publication race contour was `15 passed, 6 deselected`;
the daily-plan reservation subset was `4 passed, 15 deselected`, the
campaign auto-run/preview subset `14 passed, 17 deselected`, and the immutable
library/publication subset `12 passed, 6 deselected`. These reruns remain
worktree evidence until an authorized continuation commit and independent
review bind them to a candidate SHA.

After the receipt-replay and stale-result fences were added, the direct
campaign command/module rerun was `15 passed`; the focused auto-run/preview
rerun was `7 passed, 24 deselected`. A repeated Test request now returns the
persisted result without reaching the provider boundary, and a Stop winning
during the provider-call fixture cannot be reported as `ok=true`.

The auxiliary consumer continuation rerun was `17 passed` across the guarded
gateway, no-artificial-presence and recovery-hold fixtures; it remains local
evidence and does not authorize a live auxiliary action.

The current SDK/session compatibility rerun was `10 passed`; the lifecycle,
auth-attempt and profile-auth local subset was `22 passed`, and the platform
policy/no-artificial-action boundary subset was `11 passed`. These are not
production or live-provider evidence.

## Wave E local continuation (`T16`–`T29`)

| Case set | Result | Evidence and remaining boundary |
| --- | --- | --- |
| `T16-C01..C05` | `PASS` (local fixture scope) | Connection API/probe/resolution tests: credential redaction, assignment stability, route-version conflict, bounded duplicate probe, fragmented CONNECT/TLS stages and no OTP. `UI-C02` remains browser/human-review work. |
| `T18-C01..C04` | `PASS` (local fixture scope) | `tests/test_status_service_v2.py` covers scoped snapshots, sequence/resync, authorization and read-only separated counters. Full runtime-policy aggregation and all consumer/event paths remain open. |
| `T19-C01..C05` | `PASS` (local fixture scope) | A bounded regular-Playwright dashboard fixture passes healthy-WebSocket idle (`5.5s`), the defined two-tab/60-second rate-limit contour (`1 passed in 1.0m` on `390x844`), outage/fallback/reconnect, hidden-tab/no-poll/one-resync and `findProfile` 429/503/network error preservation contours (`3 passed` targeted rerun). The full Python compatibility rerun also passes the TestClient-backed route cases; full UI action and human visual review remain separate. |
| `T20-C01` | `PASS` (local query fixture scope) | `tests/test_summary_queries_v2.py` uses a 100,000-item library fixture and SQL trace callback to prove summary reads counts without loading `message_set_items` or full profiles. |
| `T20-C03` | `PASS` (local SQLite fixture scope) | `tests/test_tenant_isolation_sqlite.py` ran two tenant scopes concurrently, used distinct connection objects and proved that each scope retained only its own transaction marker; PostgreSQL and production-database proof remain separate. |
| `T20-C04` | `PASS` (local fixture scope) | Nine event-loop assertions include 100 actual `_authenticate_ws` cookie-auth cycles with unique JTI invalidation, bounded `tracemalloc` growth and empty session cache after retirement; the thread boundary uses the runner-compatible test shim, so this is not a live long-lived WebSocket or production memory profile. |
| `AUD20-A27-C01` | `PASS` (local fake Redis/SQLite fixture scope) | The 21-assertion continuation covers atomic count+TTL/no-TTL repair, bounded memory fallback, tenant/legacy limiter-key cleanup and cache retirement; live Redis/PG and production tenant deletion remain separate. |
| `AUD20-A46-C01` | `PASS` (local service/control fixture scope) | The 47-assertion campaign continuation exercises route Start, worker/legacy paths, persisted generation/Stop fencing, idempotent receipts and no late claim after Stop with the external adapter replaced only at its boundary. |
| `T20-C02`, `AUD20-A26-C01` | `PARTIAL` | Manual/scheduled SQLite backups, auth/status/password/Redis blocking boundaries, campaign Stop/Pause coordinator transactions and persistence, and tenant-delete cleanup now have explicit executor or bounded-cache contracts. The dynamic fixture passes with a test-only joinable-thread shim for status/backup/Stop/admin registration plus 100 WebSocket/auth cycles; source assertions retain the production `asyncio.to_thread` calls, while the restricted runner cannot complete the real default-executor shutdown path. Measured slow PG/Redis/password concurrency, production event-loop p95, live provider and production-database proof remain open. |
| `T21-C01..C04`, `T22-C01..C04`, `T23-C01..C04`, `T24-C01..C04`, `T25-C01..C04` | `PARTIAL` | UI asset, overview, message preview and admin/group backend contracts passed (`28 passed`); latest loopback browser matrix is `57 passed, 30 expected viewport-bound skips` from `87` scheduled cases, including revision-bound destination confirmation, readiness preview/test-start revision binding, auth lifecycle, OTP keyboard-height/focus flow, visible alerts, normalized error actions, RC16 reconcile/wait, bounded CSV import and command-receipt recovery. Full visual/manual acceptance and auxiliary-consumer acceptance remain open. |
| `T26-C03` | `PASS` (tenant SQLite isolation scope) | `test_diagnostic_id_from_another_tenant_is_indistinguishable_from_missing` creates a profile only in tenant 1 and proves tenant 2 receives the same `404`/message for that ID as for a missing ID. This verifies the scoped SQLite route projection, not a live PostgreSQL/auth-middleware deployment. |
| `T26-C05` | `PASS` (local Prometheus handler scope) | `test_prometheus_metric_labels_exclude_profile_and_secret_identifiers` exercises the actual local metrics handler and confirms exposed labels are limited to version/database dimensions, excluding profile, phone, proxy and attempt identifiers. Production collector/configuration behavior remains unverified. |
| `T28-C01..C04`, `T29-C03..C04` | `PASS` (local fixture/review scope) | Startup/import/route/migration, current-image dependency health, deployment-readiness failure handling, security boundary and placeholder fail-closed tests pass in the current local contour. This is not a production deploy proof. |
| `T26-C01` | `PARTIAL` (local log/status/profile/browser scope) | Credential-bearing log lines are hidden before stdout/persistence and when legacy `app_log` rows are returned by `/api/log`, `/api/status`, and the WebSocket status snapshot; request-error, tenant-delete and policy-fan-out application logs omit exception tracebacks, and an unhandled request error returns a safe structured 500 with correlation ID. Legacy profile errors are normalized before dashboard, group-profile and profile-list/detail API projections. A real-builder WebSocket regression inserts a synthetic credential-bearing legacy row and verifies the first sent snapshot contains only the safe placeholder (`1 passed`; combined WS/authz contour `35 passed`). A local server confirmed rendered “Живой лог” hid the same sentinel at 1440x1000 and 390x844. The new T26 export is restricted to current-attempt metadata and omits secrets, request/operation IDs and latency; broader cache/export projections remain unqualified, so the complete case is not accepted. |
| `T26-C04` | `PARTIAL` (local user/API/UI fixture scope) | A synthetic API 429 leaves the rendered profile `pending`, shows neither banned nor needs-reauth status, and preserves the auth attempt; middleware tests prove the profile-login handler is not called after quota exhaustion. Added a tenant-context user-only current-attempt preview/download endpoint with the exact approved seven-field allowlist and no secret values, request/operation IDs, latency or raw error text. Route regressions cover user scope, admin denial, stale-attempt 404, JSON attachment and field allowlist; the user preview/download Playwright fixture passed. Full authenticated PostgreSQL middleware/production verification is still open by design; overall T26 remains PARTIAL. |
| `T27-C01` | `PARTIAL` (local simulated viewport scope) | Test-first Playwright coverage reproduced focus loss during an asynchronous profile refresh after OTP submission. The fix preserves the selected profile action across intermediate list refreshes and watcher completion; repeated focused runs passed `5/5`. The matrix verified dialog input, Cancel and Submit controls at `390x440`, focus cycling, Enter submission, focus restoration and fixture auth. Native mobile virtual keyboard/device behavior is unavailable, so the full Master case remains open. |
| `T27-C03` | `PASS` (local OTP dialog scope) | The OTP browser flow cycles keyboard focus inside the open dialog, restores focus to the profile action on close, and confirms the next Tab moves to the following page action, so the trap does not persist after close. This is one actual local auth dialog flow; it is not evidence for every admin dialog or screen. |
| `T27-C02` | `PARTIAL` | The latest `87`-case matrix passed `57` and skipped `30` viewport-bound cases. Explicit synthetic-fixture screenshots for dashboard 503, redacted error catalogue codes, unknown-code fallback, stale dashboard and user/admin/impersonation renderers were reviewed at 390/768/1440 where exercised; no credential sentinel was visible. The prior narrow-screen toast overlap is superseded by the current 390x844/1440x1000 regression: toast notifications now sit in document flow between navigation and content and push the page instead of covering controls. Full state-by-state human screenshot review remains incomplete; this is not a visual acceptance PASS. |
| `T27-C04` | `PARTIAL` (bounded synthetic comparison) | A controlled `HEAD=7165169` versus current-dirty static-tree comparison captured dashboard-empty, dashboard-503, admin-409, impersonation-409, group-list and auth-required states at 390/768/1440 (36 screenshots total). The readiness preview, safe error/login actions, replacement of unsafe admin VDS rebuild advice, group list and public shell following synthetic restore 401 were reviewed; no screenshot was auto-updated. Group/auth showed no material visual delta; follow-up DOM replay confirms the green `campaign-btn-active` glow on “Старт” exists identically on both versions and is not keyboard focus. The previously observed narrow-screen toast overlap was corrected afterward and has dedicated viewport assertions. This is not full state acceptance; see `docs/audit/ui-review.md`. |
| `AUD20-A24-C01` | `PASS` (isolated fake transport scope) | Webhook tests reject private DNS destinations before connect, reject redirects, bound oversized/slow responses and assert the TCP destination stays pinned to the resolved public address. No webhook or external egress was made. |
| `AUD20-A36-C01` | `PASS` (isolated stubbed-script scope) | `tests/test_backup_scripts.py::test_verify_deploy_requires_actual_health_success_not_nonempty_json` runs the actual `verify_deploy.sh` twice with stubbed CLI responses: all 30 nonempty `db_ok=false` attempts exit nonzero without `verify OK`, while success only on attempt 30 exits zero. No Docker/VPS action is used. |
| `AUD20-A25-C01` | `PASS` (isolated local ingress scope) | `tests/test_ingress_security_v2.py` covers declared and actual oversized HTTP bodies, slow chunked uploads, same-origin/default-port and public mutation checks, oversized WS auth messages and bounded connection admission; `tests/test_auth_rate_limit.py` covers trusted-peer-only forwarded headers. Reverse-proxy deployment and live target behavior remain separate. |
| `AUD20-A40-C01` | `PARTIAL` (local recovery/bootstrap scope) | `tests/test_admin_recovery_v2.py` and the final isolated A40 Compose smoke exercise authorization-reference-bound password recovery, persistent auth epoch invalidation, immediate post-recovery JWT acceptance, new hash verification, and bootstrap identity/SSH-before-clone ordering; final manifest `sha256:b5dc3b1faebec3a9853d0e557c0f65a2ba0dc0cd61da4127477ee7d42dbe787b`. A real clean-host bootstrap twice and production operator authorization remain unexecuted. |
| `AUD20-A45-C01` | `PARTIAL` (local entrypoint scope) | A bounded test-mode startup followed the supported local README entrypoint and verified health, metrics, `/` and `/auth.html`; `tests/test_startup_modes_v2.py`, browser-CI and backup-script contracts added `20 passed`. VPS/bootstrap/restore/admin production commands, Windows behavior and external authorization remain unexecuted. |
| `AUD20-A38-C01` | `PARTIAL` (workflow contract scope) | `.github/workflows/deploy.yml` now accepts an exact candidate SHA, asserts checkout identity, and gates deploy on SQLite/PG/E2E, dependency, Compose/build, DR and browser jobs; local workflow/static contracts pass. A GitHub-hosted run and production environment approval were not dispatched. |
| `T26-C02` | `PASS` (local revocation/read fixture scope) | Revoked JWT is rejected by API middleware after a positive session-cache hit, the WebSocket sends no subsequent snapshot and closes `4401`, and health cookie validation runs off the event loop. Cross-process PostgreSQL race, live WebSocket, production load/p95 and diagnostic export remain unqualified. |
| `T30-C01` | `PASS` (test-reporting contract only) | Full SQLite invocation is explicitly `690 passed, 19 skipped`; the PostgreSQL modules remain disclosed rather than counted as passes in that invocation. PostgreSQL-specific modules and server E2E ran separately against pinned PostgreSQL 16 on this dirty candidate (`19 passed` + `4 passed`). A separate disposable Compose smoke against final source also reported healthy app/PostgreSQL/Redis and `db_backend=postgres` while recovery hold remained active. These are local scopes, not hosted CI or production database proof. |
| `T30-C02` | `NOT RUN` | The Master reference workload and an equivalent before/after dataset/host have not been executed. `docs/audit/performance.md` makes no performance percentage or improvement claim. |
| `T30-C03` | `PASS` (local app/HTTP/WebSocket scope) | Two real browser tabs on `390x844` stayed connected over actual local WebSockets for 60 seconds; the real local API returned 26 responses with zero 429s, each tab made zero additional `/api/status` polls while WebSocket was healthy, and no external requests or browser errors occurred. This is not a ten-subscriber/reference-load or production rate-limit measurement. |
| `T30-C04` | `PASS` (local browser fixture scope) | `reconcile and wait actions never trigger mutation or auth retries` passed in Playwright; unknown command state invokes only the read/status path, with no campaign mutation or authentication retry. The API boundary is fixture-intercepted. |
| `T30-C05` | `PASS` (local SQLite daily-plan/library scope) | `test_current_endpoint_keeps_five_items_after_two_complete_account_passes` exercises two target-five profiles against one five-item immutable library and preserves all five texts after ten accepted slots; the companion restart test preserves each account's pinned selection/library. No external send occurs. |
| `T30-C06` | `PASS` (local SQLite worker scope) | `test_claim_executes_existing_queued_slot_without_quota_recheck` proves a worker can claim its own precreated slot without rejecting the plan at the quota boundary. |
| `AUD20-E07-C01`, `AUD20-A45-C01`, `COMP-R09-C01`, `T29-C01..C02`, `AUD20-E01-C01`, `AUD20-E04-C01` | `PARTIAL` / `NOT RUN` | Related source/fixture checks exist; complete runbook exercise, image scanner database, full-history secret and repository-policy checks are not all available or authorized. Docker/health and isolated DR smoke are separately PASS for the current worktree. |

The T16/T18–T20/UI/T26–T29 local contours were `23 passed`, `18 passed`,
`28 passed` and `76 passed` respectively. The fresh writable-runner suite
recorded `617 passed, 19 skipped` in `22.73s`; the skipped modules are
PostgreSQL fixtures and do not become PASS by omission. The current full-tree
rerun with explicit restricted-runner compatibility now records `684 passed, 19
skipped` in `29.55s`; `tests/conftest.py` uses uvloop for Starlette's broken
default portal only under `MAXBOT_TESTCLIENT_UVLOOP=1` and enables a joinable
thread shim only under `MAXBOT_TEST_THREAD_SHIM=1`. The vanilla runner boundary remains recorded as
environment evidence, not an application failure; the compatibility run does
not prove production event-loop behavior. The current
worktree browser rerun used the regular Playwright fallback with Chromium
and reported `57 passed, 30 expected viewport-bound skips` from `87` scheduled cases; it
remains local, dirty-worktree evidence and does not replace the complete
UI/visual acceptance.

The current worktree follow-up added `32 passed` across T11/T33 identity,
queue and daily-plan migration/persistence/worker modules, `29 passed` across
T26/T28/T29 security/startup/policy modules and `20 passed` across focused
T21–T25 UI/backend contract modules. These are supplemental local assertions;
complete interaction/visual acceptance and external/runtime obligations remain
separate.

The A26/A27/A46 continuation added a Redis atomicity and cache-retirement
contour (`21 passed` with status/isolation fixtures), a persisted campaign
generation cross-path contour (`47 passed` across campaign auto-run, command
and module tests), and `50 passed` auth/WS authorization assertions under an
inline executor shim. The shim avoids the restricted runner's known
`asyncio.to_thread` shutdown hang; it does not prove production latency,
PostgreSQL/Redis availability or a live memory profile.

## T30–T32 release disposition

`T30` is `PARTIAL`: the latest current-worktree Docker build, earlier PostgreSQL/Redis health,
fresh server-mode Compose smoke, isolated backup/restore smoke and loopback
Playwright matrix (`57 passed, 30 expected viewport-bound skips`) are green. A
user-authorized Docker Scout scan of the latest local image found 29
vulnerabilities (0 critical, 2 high, 2 medium, 25 low); the two high Debian
package findings have no fixed version listed. The base image was updated and
runtime pip removed, but this does not pass the image security gate. Windows,
complete performance comparison and external production evidence are still
not available.
`T31` is
`NOT_ADOPTED/OFF`; no client-reuse code was enabled. `T32` remains
`BLOCKED` for final release acceptance until the exact continuation is
commit-bound, independently reviewed, and the explicitly authorized provider,
deployment and production gates are completed.

The extended matrix is a continuation gate only. It includes the task-bound
contract tests for proxy/SDK/authentication, lifecycle/recovery, ledger,
pacing, message-library/daily-plan/command order, connection/status/admin
surfaces and static UI contracts. The three skips are planned PostgreSQL
fixtures. No additional application case is promoted to `PASS` from this
aggregate result when its full Master Given/When/Then assertion set is not
covered by the executed fixture.

## Safety boundary

No real MAX action, login, SMS, send, join, probe, history/read/reaction,
provider credential, production service, deployment, push or release action
was performed. Temporary Docker fixtures, browser app data, Playwright
artifacts and dependency installation output were removed after validation.
