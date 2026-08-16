# Project Status

## Stable Areas
- Desktop local UI and smoke flow are preserved in `desktop/` (when present in parent monorepo).
- Server Docker stack is self-contained in this `server/` workspace.
- Agent Fix Plan 2026 (C/H/M/L waves) complete; SERVER-REVIEW P0–P3 complete (P3-3 main.py decomposition remains PARTIAL / ADR 003).

## Active Risks
- Core logic may exist as separate copies in `desktop/main.py` and `server/main.py`; shared fixes may need mirrored edits.
- MAX integration uses an unofficial API and can cause account, session, and security risks.
- Server mode includes auth, tenant data isolation, JWT, admin, and deployment concerns.
- Session validation cache TTL 30s; logout/delete-tenant must invalidate (implemented).

## Verification Baseline
- `MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/ -q` — **197 passed, 26 skipped** (2026-08-16, FEATURE-P3). Skips are PG skipifs + celery/pymax importorskip; CI `server-smoke` runs PG modules with `DATABASE_URL`.
- `docker compose config -q` passes when required env vars are supplied.
- Docker image pins `python:3.12-slim@sha256:…` (Dockerfile) and compose sidecars `postgres`/`redis`/`caddy` by digest; installs from `requirements.lock` + `requirements-server.lock`.
- CI installs from `requirements*.txt` (ranges); lockfiles are for reproducible Docker builds.
- Post-deploy: `curl -I https://$DOMAIN` — confirm CSP / X-Frame-Options (Caddyfile).
- Full tests in monorepo: `desktop/tests/` + `server/tests/` (CI jobs `desktop-smoke`, `server-smoke`).
