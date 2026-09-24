# T27 UI review evidence

Status: `LOCAL PASS / HOSTED CI PASS`

Current runtime/test continuation: `473eb404f374400323e9a397acb20e2818ed7637`.
The browser results below retain historical commit-bound evidence and the
restricted-sandbox attempt for provenance.

An extended 2026-09-22 loopback run against the final local candidate passed
all `21` scheduled tests across 390/768/1440. The earlier restricted attempt
was `BLOCKED` before Chromium launch because `sandbox_host_linux.cc` returned
`Operation not permitted`; that environment result is not an application
failure.

The approved local rendered-browser gate was implemented and executed on
2026-09-21 from source candidate
`e4837a1fe997d63704536f01685e56b9a97caf99`. The Browser plugin was
unavailable, so the documented regular Playwright fallback was used with real
Chromium.

## Observed local gate

The bounded fixture runner used a temporary SQLite data directory, a fixture
recovery-hold file, `MAX_TEST=1`, `MAX_SERVER_MODE=0`, and loopback
`127.0.0.1:8765`. The health response was successful and reported
`db_ok=true`, `recovery_hold=true`, and `max_external_actions=held`.

Observed commands and results:

```text
npm ci --ignore-scripts                         exit 0
npx playwright install chromium                 exit 0
.venv/bin/python -m app.main --no-browser      started in fixture process
curl -fsS http://127.0.0.1:8765/api/health     exit 0
npm run browser:e2e                             exit 0; 6 passed
```

The exact candidate rerun reported `6 passed (2.1s)` and used the same
loopback-only fixture; no MAX/provider request was made.

The matrix executed both browser specs at all required viewports:

- `390x844`;
- `768x1024`;
- `1440x1000`.

The assertions covered page identity and non-blank auth/dashboard shells,
keyboard focus and tab activation/return, an explicitly allowed local `401`
login fixture error, and a visible local recovery-hold log state. The shared
diagnostics fixture failed on unexpected console errors, page errors, failed
requests, non-2xx responses, or non-loopback requests. The passing matrix had
no unexpected diagnostics violations.

The first intentional RED run produced Playwright screenshot, video, trace,
and error-context artifacts; the final passing run did not need failure
artifacts. The workflow uploads `playwright-report/`, `test-results/`, and the
server/health logs with `if: always()`.

## Observed hosted gate

The browser branch was merged as `4d2aa28930092e8abb2917bd004ca7a2b21c07a3`
after the hosted pull-request run
(`35569486524 <https://github.com/Edifier01/maxbot/actions/runs/35569486524>`)
completed successfully. Its `browser-e2e` job ran the full three-viewport
matrix and reported `6 passed (7.4s)`; the uploaded
`maxbot-browser-diagnostics` artifact was present.

The post-merge `main` run
(`35571862150 <https://github.com/Edifier01/maxbot/actions/runs/35571862150>`)
also completed successfully. All six jobs passed: `browser-e2e`,
`server-smoke`, `server-e2e`, `compose-config`, `dependency-audit`, and
`backup-restore-smoke`.

The operator-terminal Docker check was rerun with
`docker version --format '{{.Server.Version}}'` and exited `0`, reporting
Docker Server `29.8.0`.

## Current UX extension

The current local UX extension is bound to source commit
`1d50bec847d4e41c7be6b9ed13e8fb681c2a7ee2`. Using the same regular Playwright
fallback and a temporary loopback `MAX_TEST=1` fixture, the expanded matrix
reported `12 passed (3.5s)` across 390x844, 768x1024 and 1440x1000.

The extension adds evidence for two previously manual boundaries:

- `prefers-reduced-motion: reduce` leaves no active animation or transition
  longer than the CSS accessibility budget;
- a dashboard `503` renders a visible, screen-reader-announced
  `role="alert"` with the safe "Сервис временно недоступен" message.

The 503 response and its browser console line are explicitly allowed by the
local diagnostics fixture; all other console, page-error, failed-request,
non-2xx and non-loopback checks remain strict. The candidate was exercised
against the actual temporary app fixture, with no external MAX/provider
traffic.

After the global-library/tenant-plan integration fix, the final source
candidate `36d27c3022c6e640de28ca5dbac5fbeb58d54ace` reran the same browser
matrix and reported `12 passed (3.2s)` with the same loopback-only diagnostics.

## Current structured-error regression

Source candidate `c5f52980dd7297d97ad440efe8a0fdf94997fb1b` reran the loopback-only matrix with regular
Playwright and Chromium (the Browser plugin remained unavailable) and reported
`15 passed (7.2s)` across 390x844, 768x1024 and 1440x1000. The additional
case returned a catalogue code absent from the legacy frontend fallback map
but included a server-provided redacted `safe_message`; the visible dashboard
error retained that safe message. No external origin, MAX host or provider
traffic was used.

## Current accessibility reflow and token contrast regression

The test-only accessibility extension is bound to source candidate
`24b75c3fd87385ff1af7e2284d581a9a0b558215`. The focused Python UI contracts
passed `4 passed` with the repository Python 3.12 environment. They calculate
WCAG AA contrast for the seven semantic foreground tokens against both panel
background tokens and retain the existing focus/reduced-motion contracts.

The same loopback-only Chromium fixture reported `21 passed (9.2s)` across the
existing 390x844, 768x1024 and 1440x1000 projects. The added checks set a
195x422 CSS viewport inside each project (an automated 200%-equivalent reflow
check), then verify that the auth card and dashboard main surface remain
within the viewport with visible keyboard-reachable controls. This is not a
substitute for a true browser zoom session or a manual review of every
rendered state.

## Current worktree continuation (2026-09-23)

The current source is an uncommitted continuation from baseline
`716516917e393834713e63b9f51e930b332bee38`; the Browser plugin remains
unavailable, so the regular Playwright `1.63.0` fallback was used. The latest
temporary fixture app used `MAXBOT_TEST=1 MAX_SERVER_MODE=0` with a bounded
temporary `MAX_DATA` root, `MAX_HOST=127.0.0.1`, and `MAX_PORT=8777` through
`.venv/bin/python -m app.main --no-browser`. Browser route fixtures supplied
the held/auth/error responses; no external origin or MAX/provider request was
allowed.

Observed result:

```text
BASE_URL=http://127.0.0.1:8784 npx --no-install playwright test --workers=1 --reporter=line
                                                exit 0; 44 passed, 34 skipped
```

The latest run scheduled `78` tests across `390x844`, `768x1024` and `1440x1000`.
The thirty-four skips are the expected viewport-bound cases; diagnostics
reported no unexpected console/page errors, failed
requests, non-loopback requests or unexpected non-2xx responses. Temporary
Playwright artifacts and the fixture app/data root were removed after the run.

The readiness panel now performs a read-only `/campaign/preview`, renders
blockers/warnings and the selected group/profile/library counts, and binds an
explicit Start request to the returned `readiness_revision`. The fixture
passed on all three viewports with no mutation before Preview, and a separate
390x844 screenshot/console check reported `MAX Sender`, `Готово к запуску.`
and no page or external-request errors. This remains fixture evidence, not a
live campaign or provider check.

The added destination flow renders an explicit review state after an invite-link
revision, sends only the owner-entered `chat_id` and current revision to the
loopback verify endpoint, and replaces the warning with the confirmed revision
after the response. The interaction passed on all three viewports; a separate
390x844 screenshot/console check reported `MAX Sender`, no page errors and no
external requests. This remains fixture evidence, not a live destination or
provider check.

The current error-catalogue fixture invokes every normalized action token on
visible 390px cabinet, admin and impersonation surfaces. The same rendered
matrix also exercises the bounded quoted CSV profile import fixture.
Authentication actions
end at the local login page with an explicit unauthenticated fixture response;
all other actions only open local review surfaces or issue bounded read-only
requests. No provider or MAX traffic is allowed by this fixture.

The same current matrix includes the `needs_reauth` browser lifecycle: a new
attempt reaches SMS input and completes without the watcher exiting on the
historical profile status. The focused auth case passed on `390x844` with two
expected viewport-bound skips; this is loopback fixture evidence, not live MAX
authentication.

The exact current-worktree two-tab transport contour was then rerun against a
fresh loopback fixture on `127.0.0.1:8766`: `1 passed (1.0m)`. Two tabs held
healthy WebSockets for 60 seconds with no additional status polling and no
`429`; the exact fixture process, data root, log and Playwright artifacts were
removed.

## Remaining limits

The restricted sandbox still blocks separate TestClient/thread filesystem
lifecycle runs, but the extended writable local runner for this final
candidate passed `499` tests with `19` planned PostgreSQL skips. The restricted
failure is retained as a harness limitation, not a source failure.

The current automated gate does not replace a true browser 200% zoom session,
full rendered color-contrast review, or the complete
loading/permission/stale/stop-pending matrix. Reduced motion and the
recoverable dashboard-unavailable state now have automated evidence, as do the
token contrast and narrow reflow contracts, but these results do not prove
production readiness, provider delivery, platform authorization, or a release
`GO` verdict.

No external MAX host, provider credential, login, SMS, send, join, read,
history, reaction, or proxy action was used.

## Current worktree T27-C01 OTP keyboard-height/focus continuation (2026-09-24)

The current dirty candidate is based on `716516917e393834713e63b9f51e930b332bee38`.
Browser plugin was unavailable; regular Playwright 1.63.0/Chromium was used
against a test-mode loopback app on `127.0.0.1:18770`. The API paths were
intercepted by the browser fixture; no MAX/provider requests were possible.

The focused T27-C01 browser test first failed because submitting an OTP left
focus on `body` after the loading button lost focus. The UI now restores focus
to the matching profile action after the dialog closes and after the auth
watcher refreshes the profile list. Restoration is deferred past keyboard
default handling so Enter cannot trigger an unintended second login.

The focused auth/API-429 contour passed `2` tests. The full browser matrix ran
`87` scheduled cases across `390x844`, `768x1024`, and `1440x1000`: `47 passed,
40 expected viewport-bound skips`. The new OTP case resizes Chromium to
`390x440` to simulate the usable viewport while the virtual keyboard is open,
checks the input and both actions remain visible, verifies focus trapping and
focus return, verifies the following Tab exits the closed dialog, and completes
the local fake auth flow. This closes the local OTP dialog portion of T27-C03;
other admin dialogs remain unqualified. The screenshot
`/tmp/maxbot-t27-html-report/data/539e617394493081579e72490a20772cf1b9c0f4.png`
shows the complete dialog, visible submit/cancel controls, and focus outline.

This is a reduced-viewport simulation, not a real mobile OS virtual keyboard
or device acceptance; T27-C01 remains `PARTIAL` on that boundary. The API-429
export continuation also remains `PARTIAL` until a diagnostic export path is
designed and implemented. Chromium sandbox startup required an escalated
loopback-only runner because the restricted sandbox returned
`sandbox_host_linux.cc:41 Operation not permitted`.

T27-C02 remains `PARTIAL`: several rendered error/stale states have automated
fixture assertions and contain only synthetic data, but the full state-by-state
screenshot and overlap review is incomplete. At this checkpoint T27-C04 was
`NOT RUN` because there was no checked-in/current screenshot baseline; the
later HEAD-to-dirty comparison below supersedes that status for the user
dashboard subset only.

## Current worktree T27 screenshot and viewport continuation (2026-09-24)

After expanding the renderer checks, the full static-only Playwright matrix ran
`87` scheduled tests across `390x844`, `768x1024`, and `1440x1000`: `57 passed`
and `30` expected viewport-bound skips. User, admin, and impersonation
renderers exercised all 66 structured error codes at each viewport; unknown
code fallback, stale dashboard suppression, recoverable summary failure, and
server-provided redacted catalogue messages also passed. Browser diagnostics
reported no unexpected external requests, console/page errors, failed requests,
or HTTP errors. The Browser plugin was unavailable; Playwright 1.63.0/Chromium
was used against the static-only loopback fixture with every API intercepted.

I reviewed the explicit screenshot attachments from the three viewport runs
under `/tmp/maxbot-t27-screenshot-verify-elevated-20260924` and the full-matrix
output under `/tmp/maxbot-t27-c02-final-full-20260924`. Screenshots contain only
synthetic fixture data and showed no raw-secret sentinel. At 390x844 the
transient error toast overlays the lower dashboard cards; this is a visible
overlap/polish concern, not a proven data or control failure, and keeps T27-C02
`PARTIAL`. This sample review does not qualify every UI state. T27-C04 was
still `NOT RUN` at the end of this run because there was no before-change
screenshot baseline; the later comparison below upgrades only the user
dashboard subset to `PARTIAL`.

Follow-up, 2026-09-24: the toast issue above was corrected by moving the
notification container into document flow between navigation and `main`, so a
toast pushes content instead of overlaying dashboard controls. Playwright
verified layout bounds at 390x844 and 1440x1000, and the mobile screenshot
shows the notice above the shifted campaign panel. T27-C02 remains `PARTIAL`
because complete state-by-state review is still incomplete.

The OTP focus regression was also re-run five times with a delayed profile-list
refresh after auth completion; all five passed. Focus is preserved on the same
profile action across the intermediate and final refreshes. This remains a
simulated viewport and does not prove native mobile keyboard behavior.

## 2026-09-24 HEAD-to-dirty T27 screenshot comparison

To establish a real comparison point without replacing user files, the
`static/` assets at `HEAD=716516917e393834713e63b9f51e930b332bee38` were
archived under `/tmp` and served beside a byte-for-byte copy of the current
dirty `static/` tree. Regular Playwright 1.63.0/Chromium (Browser plugin
unavailable) captured the same synthetic dashboard-empty, dashboard-503,
admin-409, impersonation-409, group-list, and auth-required states at 390x844,
768x1024, and 1440x1000 for both versions: 36 screenshots under
`/tmp/maxbot-t27-c04-*`. Each page rendered its expected title and populated
main content; static assets returned HTTP 200, `scrollY` remained zero, and
there were no page errors, failed requests, external requests, production
data, or secret sentinels. The only console/bad HTTP responses were the
expected synthetic API 503/409/401 responses. The auth-required fixture returns
401 during session restore; the app retains the public shell/login action rather
than showing a standalone error page. The group-list fixture displays a
synthetic `example.test` link only.

The reviewed differences are the candidate's read-only “Готовность к запуску”
panel, the explicit “Открыть операцию”/“Открыть вход” actions beside safe
errors, and replacement of the admin error's unsafe VDS rebuild advice with a
safe server-state/retry instruction. These match existing readiness,
normalized-error and deployment-safety contracts; no baseline was
auto-updated. Group-list screenshots showed no material baseline/candidate
delta. Auth-required leaves the same public shell in both versions. The
candidate desktop’s green “Старт” glow initially looked like a new focus ring;
a repeat of the same 401/status fixtures found the identical
`campaign-btn-active` class and computed glow on HEAD and candidate, with
`document.activeElement` on `BODY` and `:focus-visible` false in both. This is
not a focus delta. At comparison time, identical transient toasts overlaid
lower content at the narrow viewport in both HEAD and candidate. That overlap
was corrected afterward in the current worktree by placing notifications in
flow and adding viewport regression coverage. T27-C04 remains
`PARTIAL`: this is a bounded synthetic visual comparison, not full state
acceptance, and T27-C02's complete state review remains open.
