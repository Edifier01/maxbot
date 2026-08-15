# Current Context

## Product
MAX Sender is a Python/FastAPI app for controlled MAX messenger text sending with pacing, vault-protected sessions, a static UI panel, and an API.

## Repository Shape
- This workspace is the self-contained **server** tree (`server/` as Cursor root).
- In the parent monorepo: `desktop/` (Windows/PyInstaller) and `server/` stay independent.
- `.cursor/`: AI system (skills, agents, project-management).

## Current State
- **Hotfix:** MAX login `client.unsupported-version` — pin `maxapi-python==2.4.0` (app versions through 26.25.0) and pin ExtraConfig to PyMax `PREFERRED_VERSION[0]` so handshake does not sample leftover 26.14.x. Send/presence no longer leaves UI `auth_step=connecting`. Pytest **163 passed, 19 skipped**. Redeploy Docker, then «Войти» on the profile.
- **Hotfix:** campaign/send no longer requests MAX SMS. `_with_client(login_mode=False)` uses `_SessionOnlyAuthFlow`; missing session fails instead of `request_code`. Vault: InvalidToken keeps `.enc`; empty `session.db` does not overwrite a good encrypted session.
- **FEATURE-REVIEW-FIX-2026** wave 2 COMPLETE — profile proxy 403 for cabinet, vault setup/unlock/lock 410 in server mode, `delay_min_sec` API floor 5. Cookie-only CSP + CI skipif closed by FEATURE-RESIDUALS-2026. Plan: `FEATURE-REVIEW-FIX-2026.md`.
- **FEATURE-UX-OPS-2026** complete — pause holds, admin pacing copies to tenants (ADR 007), subscription extend/revoke, UI polish; tenant cabinet: groups + start/stop + stats, progress removed. Verifier PASS WITH NOTES; parent pytest **131 passed, 19 skipped**. Plan: `FEATURE-UX-OPS-2026.md`.
- **FEATURE-VAULT-CI-2026** complete — vault hot-path per-`data_dir` (`main`→`app.vault`), ADR-006, HOW-IT-WORKS `.app_key` threat model, CI Postgres on `server-smoke`, `test_vault_hot_path_isolation.py`. Verifier + security PASS WITH NOTES; parent pytest **110 passed, 13 skipped**. Plan: `FEATURE-VAULT-CI-2026.md`.
- SERVER-REVIEW-FIX-PLAN (P0–P3) done; P3-3 main.py split is PARTIAL (ADR 003).
- AGENT-FIX-PLAN-2026 (C-1…L-3) done.
- G-2 group proxy for tenant users **superseded** by FEATURE-REVIEW-FIX-2026 (API 403); impersonation/admin still can set proxy.
- Lockfiles used by Dockerfile; CI still uses loose `requirements*.txt`.
- **FEATURE-SAAS-UX-2026** complete (verifier PASS). Plan: `FEATURE-SAAS-UX-2026.md`.
- **Remember Me (persistent login)** complete — HttpOnly cookie + restore-session; checkbox default ON.
- **Admin/User panel UX follow-up** complete — admin tabs (учреждения/настройки/пул), delete-user delegation fix, +30d confirm, user dashCards on «Рассылка». Tests: 105 passed, 13 skipped.
- **FEATURE-MOBILE-2026** complete — mobile polish `@media 720px` on `static/index.html`, `admin.html`, `auth.html` (44px touch, safe-area, admin parity). Verifier PASS WITH NOTES + parent pytest **108 passed, 13 skipped**.

## AI System
Skills and agent routing — see `AGENTS.md` and `.cursor/rules/ai-skills-system.mdc`.

Active project skills:
- orchestration: `context-loading`, `start-feature`, `subagent-orchestrator`, `maxserver-harness`
- server facades: `maxserver-server-deploy`, `maxserver-fastapi-backend`, `maxserver-postgresql`, `maxserver-auth-security`, `maxserver-campaign`, `maxserver-testing`
- UI: `maxserver-static-ui`, `maxserver-ui-workflow`

Commands: `/start-feature`, `/improve-ui`, `/deploy-server`, `/ponytail-review`, `/audit-harness`.

`skills/` / Knowlange wholesale — do not load. Generics are composed from facades.

## Latest harness (2026-08-15)
Knowlange DX (no product runtime): seven `maxserver-*` facade SKILL.md files on disk; NameThatUI lookup in UI workflow; `/ponytail-review`; `/audit-harness`. Did **not** add Railway, Supabase BaaS, n8n, ECC, Agency 270, or agentmemory.

## Latest (2026-08-15) FEATURE-RESIDUALS-2026
**COMPLETE** — verifier [PASS WITH NOTES](f200e084-1724-4e7a-bc06-566254c425f0). Parent pytest **181 passed, 19 skipped**. `docker compose config -q` OK. ADR 008 cookie-only JWT. Out of scope left: main.py P3-3, to_thread, mobile P2, extra agents, `style-src` unsafe-inline. Plan: `FEATURE-RESIDUALS-2026.md`.

## Latest (2026-08-15) Plan vs Reality Review
Verifier **PASS WITH NOTES**. Product plans match code as scoped. In-scope residuals closed by FEATURE-RESIDUALS-2026.
