# Current Context

## Product
MAX Sender is a Python/FastAPI app for controlled MAX messenger text sending with pacing, vault-protected sessions, a static UI panel, and an API.

## Repository Shape
- This workspace is the self-contained **server** tree (`server/` as Cursor root).
- In the parent monorepo: `desktop/` (Windows/PyInstaller) and `server/` stay independent.
- `.cursor/`: AI system (skills, agents, project-management).

## Current State
- SERVER-REVIEW-FIX-PLAN (P0–P3) done; P3-3 main.py split is PARTIAL (ADR 003).
- AGENT-FIX-PLAN-2026 (C-1…L-3) done.
- Follow-up G-2: tenant may set group `proxy` via PATCH/CREATE in server mode (aligned with `static/index.html`).
- Lockfiles used by Dockerfile; CI still uses loose `requirements*.txt`.
- **FEATURE-SAAS-UX-2026** complete (verifier PASS). Plan: `FEATURE-SAAS-UX-2026.md`.
- **Remember Me (persistent login)** complete — HttpOnly cookie + restore-session; checkbox default ON. Tests: 104 passed, 13 skipped.

## AI System
Skills and agent routing — see `AGENTS.md` and `.cursor/rules/ai-skills-system.mdc`.

Active project skills:
- orchestration: `context-loading`, `start-feature`, `subagent-orchestrator`
- server: `maxserver-server-deploy`, `maxserver-fastapi-backend`, `maxserver-postgresql`, `maxserver-auth-security`
- app/domain: `maxserver-static-ui`, `maxserver-campaign`, `maxserver-testing`

`skills/` is a large vendored source library; do not load it wholesale.
