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
