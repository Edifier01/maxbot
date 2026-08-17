# FEATURE-REVIEW-FIX-WAVE4-2026

Full-server review follow-up. Zone: **server**. Runtime code via specialists.

## Out of scope (accepted)

- **F-14** `REGISTRATION_OPEN=1` — product decision 2026-08-17.
- **F-15** vault key beside sessions — ADR 006.

## Agent assignment

| Agent | Findings |
|-------|----------|
| campaign-specialist | F-01 deadlock, F-02 capacity, F-03 claims/DONE, F-07 flood heartbeat, F-11 antiban reload, F-16 stop_worker scope, F-12 test leak |
| database-engineer | F-04 tenant delete order |
| backend-engineer | F-10 backup path/loop, F-18 list_profiles bounds |
| security-engineer | F-06 cabinet serializers, F-09 WS revalidate |
| devops-engineer | F-05 backup/restore, F-08 deploy SHA/profile, F-13 Celery docs |
| frontend-engineer | F-17 await logout |
| qa-engineer then verifier | evidence |

## Non-goals

No Alembic, no Celery distributed ownership, no KMS, no registration default revert.
