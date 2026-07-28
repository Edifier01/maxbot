# Architecture Decisions — MAX Sender

> ADR-light log. Parent-агент добавляет записи после одобренных решений.

Format: **ADR-NNN** · date · status (accepted / superseded)

---

## ADR-001 — Dual deployment: local + server

**Date:** 2026 (project inception)  
**Status:** accepted

**Context:** Operators need portable EXE for Windows and VPS deployment with domain.

**Decision:**
- Shared core in root `main.py`
- Server differences isolated in `server/app/hooks.py` + `server/app/main.py`
- Local: `127.0.0.1`, auto-open browser
- Server: Docker + Caddy HTTPS, `0.0.0.0` internal, no browser

**Consequences:** Two entry points to maintain; hooks must stay thin until extraction.

---

## ADR-002 — SQLite default, PostgreSQL optional

**Date:** 2026  
**Status:** accepted

**Context:** EXE portability requires zero external DB. Scale path needs Postgres.

**Decision:**
- Runtime default: SQLite (`data/app.db`)
- `schema_pg.sql` + Compose profile `postgres` for future
- Enable Postgres only with `MAX_USE_DATABASE_URL=1`

---

## ADR-003 — Monolith first, extract later

**Date:** 2026  
**Status:** accepted

**Context:** MVP velocity; `main.py` is ~4700 lines.

**Decision:** Keep monolith for local/exe. Extract modules incrementally per AUDIT.md, not big-bang refactor.

---

## ADR-004 — API PIN for server exposure

**Date:** 2026  
**Status:** accepted

**Context:** Admin panel exposed via HTTPS on public domain.

**Decision:** Bearer PIN on all `/api/*` when configured. Caddy terminates TLS; app validates PIN.

---

## ADR-005 — Vanilla UI (no SPA framework)

**Date:** 2026  
**Status:** accepted

**Context:** Single admin panel, minimal deps, works in exe and Docker.

**Decision:** `static/index.html` single file. Revisit framework only if UI complexity justifies it.

---

## ADR-006 — AI agent system bootstrap

**Date:** 2026-07-28  
**Status:** accepted

**Context:** Project moving to server + UI development; need coordinated agent workflow.

**Decision:**
- Orchestrator + verifier (readonly) as core
- Domain agents: backend, frontend, database, qa, devops, security, campaign-specialist
- Project skills in `.cursor/skills/` (not the 1900 community skills in `server/skills/`)
- Feature lifecycle requires plan approval before implementation

---

## ADR-007 — Multi-tenant server (SaaS)

**Date:** 2026-07-28  
**Status:** accepted

**Context:** Server deploy needs multiple institutions (tenants), user registration, admin subscriptions, GitHub auto-deploy.

**Decision:**
- `MAX_SERVER_MODE=1` enables server SaaS features; local exe unchanged
- **Hybrid storage:** PostgreSQL for identity (users, tenants, subscriptions); per-tenant SQLite at `data/tenants/{id}/`; global admin data at `data/global/`
- JWT auth replaces API PIN in server mode
- Global message pool + antiban settings managed by admin only
- User cabinet: groups, accounts, campaign, dashboard (read-only stats)
- Admin: subscriptions, impersonation, proxy on user groups

**Consequences:** Per-request tenant context + connection pool; campaign worker scoped per tenant; PostgreSQL required on server.

---

## Pending Decisions

| Topic | Options | Notes |
|-------|---------|-------|
| Public landing page | Static site vs same FastAPI | Needed before marketing |
| CI provider | GitHub Actions vs manual deploy.sh | After repo on GitHub |
| UI framework | Stay vanilla vs lightweight (Alpine/HTMX) | After UI audit |
