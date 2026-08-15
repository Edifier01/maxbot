# Handoff

## How Future Agents Should Start
1. Determine workspace root. If opened on this server tree, paths are as written; if parent monorepo, prefix `server/` (or `maxserverapp/server/`).
2. Read `README.md` and `AGENTS.md`.
3. Read `.cursor/project-management/CURRENT_CONTEXT.md`, `PROJECT_STATUS.md`, `TASKS.md`, `DECISIONS.md`, `HANDOFF.md`.
4. For open fix plans: `AGENT-FIX-PLAN-2026.md` (complete), `SERVER-REVIEW-FIX-PLAN.md` (complete except P3-3 PARTIAL).
5. Identify whether the work targets `desktop`, `server`, or `both`.
6. Load matching **facade** skills (`maxserver-*`) from `.cursor/skills/`.
7. Use `/start-feature ...` for non-trivial changes. `/ponytail-review` after a fat diff. `/audit-harness` if skill paths 404.
8. Update these project-management files after meaningful work.

## Latest (2026-08-15)
- **FEATURE-RESIDUALS-2026 COMPLETE** — verifier [PASS WITH NOTES](f200e084-1724-4e7a-bc06-566254c425f0). REGISTRATION_OPEN default 0; CI 15 skipif isolated; cookie-only JWT (ADR 008) + CSP `script-src 'self'`; UI leftovers; Celery fail-closed. Parent pytest **181 passed, 19 skipped**. Agents: security [c11fc457](c11fc457-955d-4dd8-a3a9-3050eee29c74) [08b33072](08b33072-4d1d-4521-a439-5c7612bdd896), campaign [6baa1648](6baa1648-5cab-458d-a26b-6b56428726ba), devops [67cadf32](67cadf32-b076-477c-bd40-6fab9fcc6187) [7892d68e](7892d68e-57d5-48d3-9c9f-b8c2adf47185), frontend [a587b936](a587b936-be5e-497d-8410-7d85c4eeb166) [5f8aff05](5f8aff05-72f2-450a-a310-b59f8ed6d211), qa [5893416f](5893416f-800e-447c-be9e-583e3234d443). Uncommitted until asked.
- **Plan vs Reality Review COMPLETE** — verifier [PASS WITH NOTES](e20e90ee-a96c-47d7-9730-bb32a334795c). In-scope residuals closed by FEATURE-RESIDUALS-2026. Still deferred: main.py P3-3, to_thread, mobile P2, extra agents.
- **Harness DX (Knowlange, no product code)** — facades + `/ponytail-review` + `/audit-harness` + NameThatUI. Not installed: Railway, Supabase BaaS, n8n, ECC, DeerFlow, Agency 270, agentmemory.

## Latest (2026-08-14)
- **Hotfix: MAX client.unsupported-version** — `maxapi-python` 2.3.1→2.4.0; handshake pins current `PREFERRED_VERSION`; send no longer sticks UI on «Подключение…». Needs Docker rebuild.
- **Hotfix: campaign must not request MAX OTP** — send/presence `_with_client` no longer attaches `sms_code_provider`. Missing/empty session raises instead of `request_code`. Vault decrypt InvalidToken no longer deletes `.enc`; empty plaintext cannot clobber a good encrypted session. Pytest **160 passed, 19 skipped**.

## Latest (2026-08-13)
- **FEATURE-REVIEW-FIX-2026 wave 2 COMPLETE** — cabinet cannot write profile proxy; server vault setup/unlock/lock → 410; `delay_min_sec` API floor 5. Verifier [PASS WITH NOTES](990a477f-5db3-45f2-a238-8741b73e58ab); QA [PASS](e0a0054d-cc73-4821-bc56-bc7b9bcc85b9). Parent pytest **155 passed, 19 skipped**. Residual: cookie-only CSP, CI skipif. Uncommitted until asked.
- **FEATURE-REVIEW-FIX-2026 wave 1 COMPLETE** — API cabinet lock (pause/reset/test/schedule/retry/settings/messages/group proxy/`is_active`/bulk 403 for `role=user`); impersonation 403 on `/api/admin`; Compose `REGISTRATION_OPEN=0`; `stop_worker` no self-await; watchdog respects `auto_run`; reset re-exported; backup before upgrade; restore fail-closed. Verifier [PASS WITH NOTES](5a1474e2-4f02-48c1-8bb0-44e49c1ad2d2); QA [PASS](db0cab57-e8b4-42ef-add7-00032226ebe1). Parent pytest **148 passed, 19 skipped**. Commit `7c1e526`.
- **FEATURE-UX-OPS-2026 COMPLETE** — pause clears `auto_run`; admin settings allowlist-copy to tenant SQLite (ADR 007); subscription extend from remaining + revoke; group `is_active` PATCH + `phone=` lookup; global TXT replace resets tenant queue; UI: tenant simple cabinet (no progress), impersonation full ops, auth Enter, file upload feedback. Verifier [PASS WITH NOTES](d9ef07ec-e2be-40fb-a98f-9de1afcae56b). Parent pytest **131 passed, 19 skipped**. Residual pause/`is_active` APIs closed by REVIEW-FIX wave 1.

## Prior (2026-08-09)
- **FEATURE-VAULT-CI-2026 COMPLETE** — vault hot-path `main`→`app.vault` per-`data_dir`; shutdown encrypt per tenant; ADR-006 + HOW-IT-WORKS `.app_key` threat model; CI `server-smoke` + Postgres/`DATABASE_URL`; `tests/test_vault_hot_path_isolation.py`. Agents: security ADR [e3cb7f15](e3cb7f15-7181-4370-9671-63046d3d1166), devops [15b477e9](15b477e9-5f4a-4f40-a546-6623ef020be6), backend [ce6c2f60](ce6c2f60-8a20-4345-894f-2d71774d0b43), qa [4b9a2ee9](4b9a2ee9-9ba9-4911-bdfe-7a9b3649e378), verifier [56c95f7b](56c95f7b-5643-4db8-842f-ffea53ed94e4) PASS WITH NOTES, security spot-check [4da280c8](4da280c8-fcc5-4f8c-aca5-74ef3ece34dd) PASS WITH NOTES. Parent pytest: **110 passed, 13 skipped**.

## Prior (2026-08-08)
- **FEATURE-MOBILE-2026 COMPLETE** — P0/P1 mobile polish on `static/index.html`, `admin.html`, `auth.html`: `--touch-min: 44px`, `touch-action: manipulation`, safe-area insets, admin 16px inputs + settings-row stack + toast stretch + `#expiringTable` in `.table-scroll`, index modal-actions column-reverse / settings save full-width. P2 badge chrome deferred. Agents: ui-designer `21298e8b…`, frontend `45a7aaa9…`, qa `137129fd…`, verifier `4f903300…` (PASS WITH NOTES). Parent pytest: **108 passed, 13 skipped**.

## Prior (2026-08-07)
- **Admin/User panel UX follow-up COMPLETE** — `static/admin.html`: 3 tabs + hash; delete-user via `data-action` delegation (fix option A: broken inline onclick); subscription +30d with confirm; removed days-group. `static/index.html`: dashStats/dashCards visible to tenant users; removed `adminGlobalMode` bridge. Pytest: 105 passed, 13 skipped.
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

Do not load `skills/` or Knowlange wholesale. Active distilled skills are in `.cursor/skills/`. Facades `maxserver-*` must exist on disk; generics are composed from them.
