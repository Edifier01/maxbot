# T29 security, dependency, and secret review

Status: `PARTIAL`; this is a commit-bound local review for source candidate
`24b75c3fd87385ff1af7e2284d581a9a0b558215`, not a production release gate.
Candidate SHA is recorded above; the review is not a production approval.

## Dependency and source checks

| Check | Result | Evidence |
|---|---|---|
| `.venv/bin/pip-audit -r requirements.lock` | PASS, exit 0 | `pip-audit 2.10.1`; `No known vulnerabilities found` |
| `.venv/bin/pip-audit -r requirements-server.lock` | PASS, exit 0 | `pip-audit 2.10.1`; `No known vulnerabilities found` |
| `.venv/bin/pip check` | PASS, exit 0 | No broken requirements |
| `git diff --check` | PASS, exit 0 | no whitespace errors |
| pinned wheel/dependency review | PASS for PyMax contract | exact `maxapi-python==2.4.1` is separately recorded in verification evidence |
| Docker image build | PASS | isolated Compose project built the current app image |
| Docker image CVE scan | BLOCKED / NOT RUN | Docker Scout is available but its scan may transmit image/metadata to an external service; no such export was authorized |

The first sandboxed pip-audit attempts exited 1 while the temporary audit
environment could not resolve PyPI. The same commands were rerun with the
approved network escalation and completed with exit 0. No dependency was
changed by the audit.

The final candidate rerun at `c5f52980dd7297d97ad440efe8a0fdf94997fb1b`
repeated both lockfile audits successfully. The candidate Docker image also
built successfully in the isolated fixture builder; the image CVE scan remains
blocked because the available Docker Scout path may export image or metadata
to an external service.

The same candidate preserves server-provided redacted `safe_message` values in
both user and admin error formatters; the browser regression exercised a
catalogue code absent from the legacy fallback maps without exposing raw
exception text.

## Security boundary review

| Area | Severity | Current result | Verification |
|---|---|---|---|
| Required router imports | P1 safety | PASS | `tests/test_startup_modes_v2.py` |
| Webhook URL allowlist | P1 safety | PASS | HTTPS, explicit host, no URL credentials in `app/config.py` |
| Server WebSocket Origin | P1 safety | PASS locally | `tests/test_ws_security_v2.py`, `tests/test_security_tail.py` |
| Auth-attempt diagnostics | P1 privacy | PASS locally | `tests/test_diagnostics_security_v2.py`; queues/hints/tokens are not returned |
| tenant/auth policy and external VPS | P1/P2 | NOT RUN | no dynamic penetration test or production key rotation authorized |
| browser/console/keyboard/contrast | P1 UX/security | PARTIAL | rendered browser gate PASS; reduced-motion, recoverable offline/error state, semantic-token contrast and narrow reflow are automated; true browser zoom and full rendered-state contrast matrix remain NOT RUN |

## Secret-history scan boundary

The safe regex scan emitted filenames/counts only and never printed matching
values. Current tracked-tree scan exited 0 with no matching file. The same
pattern over all 122 reachable revisions found matches in 31 revisions, in
historical `server/skills/...` documentation paths. This pattern is not proof
that a live secret exists, but the historical matches require owner review and
possible revocation outside this task; no value is reproduced here.

The following review remains `NOT RUN`: full secret scanner/licensing inventory,
provider key rotation, and repository-host protected-branch/ruleset review.

## Limits

No external VPS, production `.env`, session cookie, OTP, proxy credential, MAX
host, provider API, Docker volume, deploy command, or real MAX action was used.
A clean dependency result does not prove absence of all security defects, and
Image CVE scan, platform authorization, remaining manual UX evidence, and
production evidence remain release blockers.

Live platform authorization and MAX qualification remain `BLOCKED`; no
provider, VPS, credential, or external action was used by these gates.
