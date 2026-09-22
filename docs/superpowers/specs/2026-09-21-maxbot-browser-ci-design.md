# MAXBOT browser CI design

Status: proposed design approved in chat; implementation is not started.

## Intent

Add a reproducible rendered-frontend gate for MAXBOT without contacting MAX,
using real Chromium in an isolated CI job and deterministic local fixtures.
The gate must cover the three required widths (390, 768, and 1440 CSS px),
keyboard/focus behavior, console and failed-request health, and the visible
recovery-hold/held-action states.

This is a dirty-worktree change. It must not commit, push, merge, deploy, add
production dependencies, or qualify a real MAX account.

## Current context

- The application is a FastAPI server that serves `/`, `/auth.html`, and
  `/admin.html` plus `/static/*`.
- The repository already has Python fixtures and a `MAX_TEST=1` boundary, but
  it has no Node package manifest, Playwright configuration, or browser CI job.
- Existing GitHub Actions use pinned action SHAs and Python 3.12. The browser
  job follows the same immutable-action convention.
- The current Browser plugin is unavailable, so CI uses the documented regular
  Playwright fallback with an explicit local-only network guard.

## Scope

### In scope

1. A dev-only npm manifest and lockfile with an exact `@playwright/test` version.
2. A Playwright configuration with three viewport projects:
   - `390x844`;
   - `768x1024`;
   - `1440x1000`.
3. Browser smoke specs under `tests/browser/` covering:
   - page identity and non-blank rendering for the auth and main surfaces;
   - auth-panel/tab interaction and keyboard focus/activation;
   - deterministic held/recovery-hold presentation using local API fixtures;
   - console errors, failed requests, and external-host attempts;
   - screenshots/traces on failure.
4. A separate `browser-e2e` GitHub Actions job that installs the pinned Python
   and Node dependencies, installs Chromium, starts MAXBOT in local test mode,
   waits for `/api/health`, and runs the matrix.
5. CI artifact upload for Playwright report, screenshots, and traces on failure.

### Out of scope

- Any real MAX host, MAX login, SMS, send, join, read, history, reaction, or
  proxy probe.
- Changes to product UI behavior or production Python dependencies.
- Production database migrations, Docker image runtime, deployment, or live
  authorization qualification.
- Treating a successful browser render as proof of provider delivery or
  production readiness.

## Design

### Tooling boundary

Use the Node Playwright runner because the repository has no browser test
framework and the target is vanilla JavaScript. `package.json` exposes a
single `browser:e2e` script; `package-lock.json` makes installation
reproducible. Playwright is a development/CI dependency only and is not copied
into the production Docker image.

The configuration receives `BASE_URL` from CI, defaults to
`http://127.0.0.1:8765`, and does not start a second application process. CI
owns application startup so Python dependency failures are visible in the
job log and the browser runner remains frontend-focused.

### Application fixture

CI installs the existing locked Python dependencies, starts
`python -m app.main --no-browser` with:

- `MAX_TEST=1`;
- `MAX_SERVER_MODE=0`;
- a temporary `MAX_DATA` directory;
- a temporary `MAX_RECOVERY_HOLD_FILE` fixture so the held state is
  deterministic;
- a fixture-only `JWT_SECRET`;
- `MAX_HOST=127.0.0.1` and `MAX_PORT=8765`.

The server is readiness-checked through `/api/health`. Browser specs mock only
local application API responses needed to render authenticated/held states;
they never mock or call a MAX endpoint. The app's external-action hold remains
visible and no provider credentials are present.

### Browser safety guard

Every test context records requests and fails if a request leaves the local
origin (`127.0.0.1`, `localhost`, or the configured `BASE_URL`). The guard
also fails on console errors and failed HTTP requests unless a test explicitly
declares an expected fixture response. This makes an accidental external
transport attempt a hard CI failure.

### Test flow

The primary flow under test is:

`/auth.html` loads -> auth UI renders -> keyboard changes the selected auth
panel -> local fixture response renders the expected held/error state.

A secondary flow checks:

`/` loads -> visible dashboard shell renders -> the local held/recovery state
is visible without a MAX request.

Each flow runs in all three viewport projects. The specs assert visible DOM
state and focused elements; screenshots and traces are diagnostic artifacts,
not the only proof.

## Files

Create:

- `package.json`;
- `package-lock.json`;
- `playwright.config.js`;
- `tests/browser/fixtures.js`;
- `tests/browser/auth.spec.js`;
- `tests/browser/dashboard.spec.js`.

Modify:

- `.github/workflows/ci.yml` — add the isolated `browser-e2e` job;
- `docs/audit/ui-review.md` and `docs/audit/verification.md` — record the
  actual CI result without claiming production readiness.

Do not modify production dependency lockfiles or application behavior unless a
browser regression proves a separate source bug; such a bug gets its own RED
test and scope decision.

## Acceptance criteria

- `npm ci` succeeds from the committed lockfile.
- Chromium installation succeeds in the CI runner.
- `npm run browser:e2e` executes all three viewport projects.
- The gate records page identity, non-blank content, interaction/focus,
  console, failed-request, and local-only network results.
- A test or application failure produces Playwright artifacts.
- No browser test opens a non-local URL or performs a MAX action.
- The browser job is independent of the PostgreSQL skipif jobs and does not
  change their environment.
- The final release remains `FIX` until the browser result is combined with
  independent platform-authorization review, Master integration evidence, and
  commit-bound verification.
