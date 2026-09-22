# T27 UI review evidence

Status: `LOCAL PASS / HOSTED CI PENDING`

The approved local rendered-browser gate was implemented and executed on
2026-09-21 from the current dirty worktree. The Browser plugin was unavailable,
so the documented regular Playwright fallback was used with real Chromium.

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

## Remaining limits

The GitHub-hosted `browser-e2e` job has not been executed from this workspace;
its workflow/static contract is covered by `tests/test_browser_ci_contract.py`.
Hosted CI remains `PENDING` until a runner executes the checked-in workflow.

The current automated gate does not replace separate manual/automated checks
for 200% zoom, contrast, reduced motion, offline behavior, or the full
loading/permission/stale/stop-pending matrix. These results do not prove
production readiness, provider delivery, platform authorization, or a release
`GO` verdict.

No external MAX host, provider credential, login, SMS, send, join, read,
history, reaction, or proxy action was used.
