# Handoff

## Last session

2026-08-07 — Linked local `Projects/server` to `Edifier01/maxbot` and converted remote to server-only.

## Done

- `git remote` → https://github.com/Edifier01/maxbot.git
- Branch `chore/server-only-repo` @ `8692402`: server tree at repo root; removed `desktop/`, nested `server/`, and skills dumps
- Local backup kept at `Projects/_server_backup_20260807_155238` (can delete after merge)

## Next action

1. Merge PR for `chore/server-only-repo` into `main`
2. `git checkout main && git pull`
3. Optionally delete stale branch `cursor/milestone-5-production-readiness` (old monorepo layout)
4. First product Feature Plan, e.g.:

```text
/start-feature Harden Celery vs in-process campaign start parity (tenant headers + INTERNAL_SERVICE_TOKEN) with tests
```

## Blockers

PR merge required for `main` to match local server-only layout.

## Notes for next agent

- Read `AGENTS.md` + this file + `CURRENT_CONTEXT.md` first.
- Do not reintroduce `desktop/` or bulk skill catalogs into this repo.
- Payments are out of scope.
