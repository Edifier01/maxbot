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

## Latest (2026-08-16)
- **UI polish COMPLETE** — Vercel `web-design-guidelines` from https://www.skills.sh/vercel-labs/agent-skills/web-design-guidelines (`npx skills add`, `skills-lock.json`). Panels share tokens/chrome/a11y. Verifier [PASS WITH NOTES](76f02d26-dac8-4acc-876c-8f41a963a602). Agents: ui-designer [ee64f9e5](ee64f9e5-ef8d-4d05-8aae-34c29394df69), frontend [270b118d](270b118d-7a63-4276-9da1-1fee394e3053), qa [0e5f1f76](0e5f1f76-5c0d-4c26-bc5d-83afdd21a702). Pytest **14 passed** (`test_saas_ux_static.py`). Residual: generated admin `type="button"`; auth tabs Home/End. Uncommitted until asked.
- **FEATURE-CABINET-ACTIVITY-2026 COMPLETE** — verifier [PASS WITH NOTES](0a8eaed0-248a-4e34-bda6-312127ca3641). Targeted pytest **68 passed**. Agents: campaign [47e563b4](47e563b4-24ef-4cc0-89f5-b3a6c7eed56c), backend [98b0eb88](98b0eb88-7266-4757-bef7-eed921ccf339), frontend [a224a97f](a224a97f-6017-47db-94c8-1d1dfec5b268), security [45e89e2e](45e89e2e-000b-46d2-a15c-5a3e77b4094b). Residual: `/api/send_log` still returns `sent_text` to role=user if called directly (UI hidden). Uncommitted until asked.
- **FEATURE-P3-REVIEW-FIX-2026 COMPLETE** — verifier [PASS WITH NOTES](ceb43ba6-7e23-4fc7-b5d1-4270fb71cb39). Pytest **197 passed, 26 skipped**. `docker compose config -q` OK. Agents: campaign [29c147d7](29c147d7-8776-4867-8162-7d9a239ad1fa), backend [ec8828aa](ec8828aa-d013-4a6a-b45b-e46cc757fdbc), devops [2e08537a](2e08537a-10fd-4a34-b50c-57520c1f4e2a), qa [e1440654](e1440654-12a6-48d9-b7d2-f00af26e5dd7). Out of scope: style-src, PIN vault, main.py split, Docker USER, to_thread. Uncommitted until asked.
- **FEATURE-P2-REVIEW-FIX-2026 COMPLETE** — verifier [PASS WITH NOTES](5b0f7201-a7a5-42f5-a525-27c5494bb02f). Pytest **191 passed, 26 skipped**. Agents: security [662e61d0](662e61d0-9bbc-48ed-8067-2bdb19c2f376), campaign [6e1d4ae1](6e1d4ae1-34ef-4834-89cb-56a0644f8a9a), backend [bb6ce709](bb6ce709-47e1-49c4-9577-29524675442c). Skipif now requires `psycopg_pool` too. Uncommitted until asked.
- **FEATURE-P1-REVIEW-FIX-2026 COMPLETE** — verifier [PASS WITH NOTES](9e85f29c-be39-4884-bebe-5476525fcda0). Parent pytest **64 passed** (P1 + related files). `docker compose config -q` OK. Agents: security [ea430d6d](ea430d6d-7f6f-40c0-baea-81781b479a24), campaign [92d2ac9c](92d2ac9c-2373-4539-93a3-1f46441dd0fa), devops [2f4a182b](2f4a182b-53aa-47da-8667-6ce3b6789797), qa [12977a85](12977a85-2dc9-4a8e-89fd-2e42d68a5a4a). Uncommitted until asked. Residual: `_log` still written globally; restore swap before pg_restore (if PG fails, data is new); full local pytest still 12 fail/14 error without celery/psycopg.

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
- Per-tenant `CampaignRuntime.claim_lock` (FEATURE-P3); process-global `main._claim_lock` removed.

## Important Rule
Specialist agents must not edit project-management state independently. The parent agent owns integration and handoff updates.

## Skills Library

Do not load `skills/` or Knowlange wholesale. Active distilled skills are in `.cursor/skills/`. Facades `maxserver-*` must exist on disk; generics are composed from them.
