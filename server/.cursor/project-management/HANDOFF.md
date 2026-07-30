# Handoff

## Completed (2026-07-30) — Milestone 5

- Register rollback, Redis auth rate limit
- Health/metrics extensions, ops_monitor, subscription_jobs
- Admin expiring API/UI, user subscription date in index.html
- main.py restored after accidental git revert
- Worker extraction deferred (ADR 003)

### Validation

```
MAX_TEST=1 MAX_SERVER_MODE=1 JWT_SECRET=test-secret-min-32-chars-long python -m pytest tests/ -q
→ 44 passed, 4 skipped
```

## Backlog

- Worker monolith refactor (ADR 003)
- Billing (out of scope)
