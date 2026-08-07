# Decisions

## 2026-07-28: Two Independent Versions
Desktop and server are separate working folders. The server Docker build uses `server/` as context. Desktop does not depend on server extensions.

## 2026-07-28: One Common AI System
Use a single root `.cursor/` system for both versions. It coordinates work through shared project-management files while rules scope implementation to `desktop/**` or `server/**`.

## 2026-07-28: Minimal Agent Set
Created only agents justified by this product: orchestrator, verifier, backend, frontend, database, QA, DevOps, security, and campaign/domain specialist.

## 2026-07-28: Dual Workspace Bridge
Canonical project root is `maxserverapp/`. If Cursor is opened at the parent `MaxServer/MaxServer` folder, root `AGENTS.md` and `.cursor/rules/workspace-root.mdc` redirect agents to `maxserverapp/`.

## 2026-07-28: Vendored Skills Library
`skills/` is a large source library, not active AI context. Active project skills live in `.cursor/skills/` and contain distilled guidance from relevant source skills.

## 2026-08-07: Tenant group proxy in server mode
Tenant UI may set group `proxy` via `POST/PATCH /api/groups` in server mode. Validation via `antiban_core.normalize_proxy_field`. Admin `PUT /api/admin/tenants/.../proxy` remains for ops/impersonation.

## 2026-08-07: Lockfiles for Docker only
`requirements.lock` / `requirements-server.lock` pin Docker installs. CI continues to install from `requirements*.txt` ranges unless flaky CI forces parity.

## 2026-08-07: Specialist delegation gate
After `/start-feature` + proceed, parent must implement via Task specialists per Agent Assignment (rule: `.cursor/rules/specialist-delegation.mdc`). Exceptions: explicit user override, LOW ≤2 files non-security, PM/docs-only.

## 2026-08-07: SaaS UX — product decisions (Feature SaaS UX 2026)

- **Banned status:** explicit `profiles.status = 'banned'` in per-tenant SQLite when ban detected (not UI-only heuristic).
- **Message pool:** admin-only upload; users without subscription cannot start campaigns; no user self-serve pool.
- **Admin UI:** global settings/messages sections on main admin screen (not per-tenant inline for pool).
- **Worker pool:** default `worker_pool_size = 1` for all tenants; only admin may change per user via admin API/UI.

Plan: `.cursor/project-management/FEATURE-SAAS-UX-2026.md`

## 2026-08-07: Remember Me — persistent login

- **Default:** checkbox «Запомнить меня» **включён** на login/register.
- **Persistence:** HttpOnly cookie `max_token`, `Max-Age = JWT_EXPIRE_HOURS` (168 h default); отдельный `JWT_REMEMBER_HOURS` не нужен.
- **Session tab:** JWT в `sessionStorage` для Bearer/WS; cookie восстанавливается через `POST /api/auth/restore-session`.
- **Impersonation:** persistent cookie **не** ставится; restore отклоняет `imp=true`.

## 2026-08-07: UI improvement workflow (Knowlange)

Skills from `Knowlange/agentic-awesome-skills` adapted into `.cursor/skills/`:

- `maxserver-ui-workflow` — pipeline orchestration
- `ui-ux-pro-max` — design system CLI + data (full copy)
- `web-design-guidelines` — Vercel audit
- `frontend-design-max` — visual brief (vanilla CSS constraints)
- `maxserver-static-ui` — panel conventions (was referenced, now present)

Agent: `ui-designer` (readonly audit). Command: `/improve-ui`. Implement: `frontend-engineer`.
