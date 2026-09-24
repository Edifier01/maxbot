# T29 security, dependency, and secret review

Status: `PARTIAL`; this is a commit-bound local review for runtime/test
candidate `473eb404f374400323e9a397acb20e2818ed7637`, not a production release
gate. Historical evidence rows retain the SHAs on which those checks actually
ran; this review is not a production approval.

The current restricted environment cannot reach the Docker daemon, so image
build/CVE checks are not rerun here. This is recorded as `BLOCKED`, not as a
clean image-security result.

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

## 2026-09-24 authorized current-image scan continuation

The user authorized Docker Scout metadata transfer for exact local image
`sha256:aeac47f0eb2c427e4c1bee78e4df3edb3410c69383da4e587ced4ba04e414951`
(T08 file-lock fix included; no publication or deployment). Scout indexed 190
packages and reported 29 findings in 12 packages: 0 critical, 2 high, 2 medium,
25 low. The high findings are CVE-2026-82560 against Debian `perl
5.40.1-6+deb13u1` and CVE-2026-85091 against Debian `zlib
1:1.3.dfsg+really1.3.1-1`; Scout lists no fixed version for either. Local
applicability inspection found `Pod::Text` absent (Perl reports it cannot
locate the module) and the application has no `gz*` zlib API calls; `tarfile`
is used in the restore script. These are bounded reachability observations,
not proof of non-exploitability, a finding suppression, or owner risk
acceptance. Keep the image gate `FIX/PARTIAL` until a vendor-fixed image is
scanned or the owner explicitly accepts the residual risk. No new base distro
or manual system-library patch was introduced.

## Security boundary review

| Area | Severity | Current result | Verification |
|---|---|---|---|
| Required router imports | P1 safety | PASS | `tests/test_startup_modes_v2.py` |
| Webhook URL allowlist | P1 safety | PASS | HTTPS, explicit host, no URL credentials in `app/config.py` |
| Server WebSocket Origin | P1 safety | PASS locally | `tests/test_ws_security_v2.py`, `tests/test_security_tail.py` |
| Bounded HTTP/WS ingress and trusted proxy headers | P1 safety | PASS locally | `tests/test_ingress_security_v2.py`, `tests/test_auth_rate_limit.py`; reverse-proxy/production behavior remains unverified |
| Administrator recovery/session invalidation | P1 auth | PASS locally | `app/admin_recovery.py` + control-volume auth epoch claim; old JWTs fail closed and an immediate post-recovery JWT is accepted in the isolated PostgreSQL smoke; operator authorization remains separate |
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

The 2026-09-23 exact-worktree continuation repeated a read-only aggregate scan
without printing paths or values: private-key/provider-token/JWT/password-like
pattern file counts were `10/2/0/0/19/39` respectively, and
`git fsck --full --strict --no-progress` passed. Broad matches are not proof of
live credentials; the result remains blocked on owner classification,
revocation review and a complete approved scanner/licensing inventory.

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
