# MAXBOT browser CI implementation plan

> **For agentic workers:** Execute this plan task by task. Keep the existing dirty worktree intact and do not commit unless explicitly authorized.

**Goal:** Add a reproducible Chromium browser gate for the rendered MAXBOT auth and dashboard surfaces in an isolated CI job, without any MAX/provider traffic or production dependency changes.

**Architecture:** The GitHub Actions `browser-e2e` job installs the existing locked Python dependencies and dev-only npm dependencies, starts the local FastAPI app in `MAX_TEST=1` SQLite mode with a temporary recovery-hold fixture, waits for `/api/health`, then runs Playwright against the already-running app. Playwright uses three viewport projects, local-only request guards, fixture responses for the held/auth states, and failure artifacts.

**Tech Stack:** Node/npm, `@playwright/test` 1.63.0, Chromium, FastAPI static pages, Python 3.12, GitHub Actions.

**Approved spec:** `docs/superpowers/specs/2026-09-21-maxbot-browser-ci-design.md`

## Global constraints

- Work in the current checkout; preserve all existing tracked and untracked user changes byte-for-byte outside the scoped files.
- Do not commit, push, merge, deploy, contact MAX, use provider credentials, or change production Python/Docker dependencies.
- Use `apply_patch` for authored file edits. Generated `package-lock.json` may be produced by npm from the authored manifest.
- Use npm consistently because this repository has no existing JavaScript package manager or lockfile.
- The browser job must be independent of PostgreSQL jobs and must use only loopback application URLs.
- A browser pass proves only the local rendered gate; it does not change the overall release verdict or prove production readiness.

## Review focus

- Browser tests must fail on non-local requests, unexpected failed responses, and console errors while allowing explicitly declared deterministic fixture failures.
- Tests must assert visible content and keyboard/focus behavior, not only HTTP status or DOM existence.
- Recovery-hold evidence must be deterministic and must not invoke any MAX action.
- The CI startup/cleanup path must expose Python startup failures and upload Playwright diagnostics on failure.
- Final docs must report only commands and exit codes actually observed; do not claim GitHub-hosted execution when only local validation was run.

## Task 1: Add the reproducible browser runner contract

**Files:** Create `tests/test_browser_ci_contract.py`, `package.json`, `playwright.config.js`; generate `package-lock.json`.

1. Write Python contract tests first. They read the repository files and assert:
   - the npm manifest has only `@playwright/test` as a dev dependency, pinned exactly to `1.63.0`;
   - `browser:e2e` invokes Playwright through the checked-in configuration;
   - the Playwright config has the default loopback `BASE_URL`, three exact viewport projects (`390x844`, `768x1024`, `1440x1000`), failure artifacts, and no web server command;
   - the manifest and config do not contain MAX/provider hostnames or credentials.
2. Run the focused contract test and record the expected RED failure because the browser runner files do not yet exist.
3. Add the minimal npm manifest with `private: true`, `browser:e2e: playwright test`, and exact dev dependency `@playwright/test: 1.63.0`.
4. Add `playwright.config.js` using `defineConfig`, `BASE_URL || http://127.0.0.1:8765`, three named viewport projects, `use.baseURL`, `trace: 'retain-on-failure'`, `screenshot: 'only-on-failure'`, and `video: 'retain-on-failure'`; do not configure `webServer`.
5. Run `npm install --package-lock-only --ignore-scripts` and `npm ci --ignore-scripts` to create and validate the exact lockfile without installing production packages.
6. Run the focused contract test again and record GREEN.

## Task 2: Build the local-only Playwright fixture and auth coverage

**Files:** Create `tests/browser/fixtures.js`, `tests/browser/auth.spec.js`.

1. Add a shared fixture that installs per-page listeners for `console` errors, failed requests, non-2xx responses, and request URLs. Permit only loopback URLs and the configured `BASE_URL`; throw on any other origin. Expose a helper for explicitly allowing a deterministic expected response.
2. Configure fixture teardown to attach the collected browser diagnostics to the test result and fail the test when an unexpected console error, request failure, non-2xx response, or external-origin attempt occurred.
3. Add auth smoke tests for every viewport project:
   - load `/auth.html`, assert title `MAX Sender — Вход`, visible `MAX Sender`, login/password controls, and non-empty rendered card;
   - use keyboard navigation to focus the login and password controls, submit invalid local credentials through a `page.route` fixture, and assert the visible local error state without calling any non-local URL;
   - assert the page remains within the configured local origin and capture focused element evidence.
4. Run the auth spec against a started local app and observe the expected RED result if the fixture/spec contract exposes a real application issue; fix only a browser-scope issue with a separate regression test and explicit scope note.

## Task 3: Add the dashboard and recovery-hold browser coverage

**Files:** Create `tests/browser/dashboard.spec.js`.

1. Add local route fixtures for the minimal unauthenticated/server responses needed by the static dashboard bootstrap (`/api/health`, restore-session, auth/me, vault/status, and dashboard/status endpoints as observed from source). Keep all responses local and deterministic.
2. Load `/` at all three viewport projects and assert the dashboard identity (`MAX Sender`), visible campaign shell, non-blank main content, and no full-page error overlay.
3. Assert keyboard tab navigation: focus `tab-campaign`, press `ArrowRight`, assert `tab-messages` is focused and selected, then return with `ArrowLeft` and assert campaign is active. Do not assert hidden tabs as visible.
4. Return a deterministic recovery-hold payload from the local fixture and assert the visible held/recovery state in the dashboard status/banner/log surface. Assert no request URL leaves loopback.
5. Run the focused browser specs after starting the app with a temporary data directory and recovery-hold file; record the actual pass/fail counts and artifacts.

## Task 4: Add the isolated GitHub Actions browser job

**Files:** Modify `.github/workflows/ci.yml`.

1. Add an independent `browser-e2e` job on `ubuntu-latest` with checkout and setup actions pinned to the repository’s existing immutable SHAs.
2. Set up Python 3.12 and Node 24, install `requirements.lock`, `requirements-server.lock`, and `requirements-dev.txt`, then run `npm ci` and `npx playwright install --with-deps chromium`.
3. Create only runner-temporary data and recovery-hold paths. Start `python -m app.main --no-browser` with `MAX_TEST=1`, `MAX_SERVER_MODE=0`, loopback host/port, fixture-only JWT secret, `MAX_DATA`, and `MAX_RECOVERY_HOLD_FILE`; keep the PID and use a shell trap to terminate it.
4. Poll `/api/health` with a bounded loop before invoking `npm run browser:e2e`; fail with the application log if readiness is not reached.
5. Upload `playwright-report/`, `test-results/`, and the captured server log with `if: always()` and `retention-days: 7`.
6. Add no secrets, MAX hosts, production environment, PostgreSQL service, or changes to existing jobs.
7. Run YAML/static contract tests and inspect the workflow diff for shell quoting, cleanup, and artifact paths.

## Task 5: Validate locally and update audit evidence

**Files:** Modify `docs/audit/ui-review.md` and `docs/audit/verification.md` only after evidence exists.

1. Install Chromium in the local Playwright cache if needed, start the app in the same bounded temporary fixture mode, and run `npm run browser:e2e` with all three projects.
2. Run the browser contract tests and the relevant Python tests; run `git diff --check` and inspect the complete scoped diff.
3. Record exact observed browser commands, project counts, exit codes, and any unavailable hosted-CI verification in the audit docs. State that the Browser plugin was unavailable and regular Playwright was used if that remains true.
4. Keep the overall release status `FIX` until the independent platform-authorization review, Master integration evidence, CVE/secret-history review, and commit-bound verification are separately complete.

## Task 6: Final self-review and handoff

1. Re-read the approved spec, this plan, all new browser files, the workflow job, and the audit diff.
2. Check for external URLs, credentials, generated caches, screenshots, reports, logs, and accidental edits outside scope; remove only newly generated disposable artifacts if they are not ignored and are clearly ours.
3. Run the final focused checks, report exact results, list changed files, and identify any blocker without masking it as a pass.
4. Do not commit or alter unrelated dirty worktree changes.
