# Handoff

## How Future Agents Should Start
1. Determine workspace root. If opened on `server/`, paths are as written; if parent monorepo, prefix `server/` (or `maxserverapp/server/`).
2. Read `README.md` and `AGENTS.md`.
3. Read `.cursor/project-management/CURRENT_CONTEXT.md`, `PROJECT_STATUS.md`, `TASKS.md`, `DECISIONS.md`, `HANDOFF.md`.
4. For open fix plans: `AGENT-FIX-PLAN-2026.md` (complete), `SERVER-REVIEW-FIX-PLAN.md` (complete except P3-3 PARTIAL).
5. Identify whether the work targets `desktop`, `server`, or `both`.
6. Load matching project skills from `.cursor/skills/`.
7. Use `/start-feature ...` for non-trivial changes.
8. Update these project-management files after meaningful work.

## Latest (2026-08-07)
- **Remember Me (persistent login) COMPLETE** — `remember_me` default true; HttpOnly `max_token` cookie; `POST /api/auth/restore-session`; UI checkbox in `auth.html`; boot restore in `index.html`/`admin.html`. Pytest: 104 passed, 13 skipped.
- **FEATURE-SAAS-UX-2026 COMPLETE** — verifier PASS. Pytest: 100 passed, 7 skipped.
- **`/improve-ui` Phase A+B+C DONE** — tokens, a11y, Manrope, Phase C: skip link, modal trap, hash tabs, Intl dates. Pytest: 100 passed.
- Agent Fix Plan 2026 waves 1–4 implemented and marked DONE.
- G-2: removed server-mode strip of group `proxy` on create/PATCH; test `tests/test_group_proxy_server.py`.
- G-4 decision: keep `*.lock` for Docker only; CI stays on `requirements*.txt`.
- Dead `CampaignRuntime.claim_lock` removed (claim uses `main._claim_lock` asyncio.Lock).

## Important Rule
Specialist agents must not edit project-management state independently. The parent agent owns integration and handoff updates.

## Skills Library

Do not load `skills/` wholesale. It is a vendored reference library; active distilled skills are in `.cursor/skills/`.
