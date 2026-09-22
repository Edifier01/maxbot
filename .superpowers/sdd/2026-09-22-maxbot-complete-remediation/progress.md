# SDD ledger — plan: docs/superpowers/plans/2026-09-22-maxbot-complete-remediation.md

## Baseline

- Workspace: `/tmp/maxbot-complete-remediation`
- Branch: `codex/complete-production-remediation`
- Base SHA: `a7b62704c1e6ceed5d01d1105649a480903806cb`
- User direction: integrate the candidate work, reconcile docs/config, verify locally, and prepare `main`; do not substitute local evidence for production proof.

## Plan scan

| Task | Shared files/interfaces | Check | Ruling |
|---|---|---|---|
| 1 -> 2 | `app/campaign_worker.py`, daily-plan test | Task 1 reproduces the pre-fix failure; Task 2 applies the existing candidate fix | Apply candidate only after RED evidence |
| 2 -> 3 | audit docs and policy files | Task 2 imports historical candidate evidence; Task 3 rebases status/configuration to the final candidate | Preserve historical records, add current final-SHA status, do not claim external gates |
| 2 -> 4 | code/tests/browser contracts | Task 4 verifies the integrated tree, not an earlier candidate SHA | Run all checks on the final tree |
| 3 -> 4 | `.env.example`, compose, docs | Documentation changes do not change runtime behavior; verification checks syntax and config | Keep changes narrow and inspect diff |
| 4 -> 5 | final SHA and status | Task 5 is gated by fresh verification | Do not merge/push a failed result |

## Rulings

- Ruling: use the candidate commits as the implementation source for already-reviewed code fixes — the user explicitly requested completing the prior audit findings, and reimplementing them would create unnecessary drift.
- Ruling: treat live MAX, production, Docker image metadata, GitHub push, and deploy as external gates — they cannot be replaced by local tests or silently executed.

## Task 1

- [x] Baseline RED run: the focused test failed with `WaitDecision(waiting_pool_or_no_queued_slot)`.
- Root cause: the test passed `main._local_now()`, which is a naive UTC+3 wall-clock value, into `business_date_utc3()`, whose documented naive input contract treats naive values as UTC. After 21:00 Moscow this advanced the claim date by one day. Production `_claim_daily_job_sync()` passes an aware UTC timestamp; the test now uses the same contract.
- Ruling: correct the test clock input rather than change production date semantics — changing the service would alter the explicit UTC-aware boundary and could mislabel callers that pass naive UTC.

## Task 2

- [x] Candidate commits integrated as 14 local cherry-pick commits.
- [x] Related tests green: 71 passed after the UTC-aware daily-plan test correction.

## Task 3

- [x] Policy documentation/configuration reconciled: one worker, UTC+3, fixed-third roles, inactive presence controls, and honest audit status.

## Task 4

- [x] Final combined focused integration/policy checks passed: 150 tests.
- [x] Static/source/config checks passed; 518 tests collected.
- [x] Extended local full suite passed: `499 passed, 19 skipped`; the restricted-host timeout remains recorded as a harness limitation.
- [x] Extended loopback browser matrix passed `21`; the restricted Chromium launch remains recorded as a harness limitation. Docker daemon remains `BLOCKED` by socket permissions.

## Task 5

- [ ] Final branch reviewed and prepared
