# T27 UI review evidence

Status: `LOCAL PASS / HOSTED CI PASS`

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

## Remaining limits

The local full Python suite is not authoritative in the restricted sandbox:
separate runs block in TestClient/thread filesystem lifecycle tests. The
writable Python 3.12 container run for this exact candidate passed `499` tests
with `19` planned PostgreSQL skips.

The current automated gate does not replace a true browser 200% zoom session,
full rendered color-contrast review, or the complete
loading/permission/stale/stop-pending matrix. Reduced motion and the
recoverable dashboard-unavailable state now have automated evidence, as do the
token contrast and narrow reflow contracts, but these results do not prove
production readiness, provider delivery, platform authorization, or a release
`GO` verdict.

No external MAX host, provider credential, login, SMS, send, join, read,
history, reaction, or proxy action was used.
