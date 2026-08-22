# Codebase Audit — MAX Sender Server

**Mode:** `/audit-project` phase 1  
**Target:** `C:\Users\Maga\Documents\Projects\server`  
**Generated:** 2026-08-07  
**Auditor:** project-architect  

---

## 1. Product summary

**MAX Sender** — multi-tenant Russian SaaS for controlled bulk messaging in the MAX messenger. Organizations (tenants) register, receive a manually granted subscription, manage MAX accounts (vault-encrypted sessions), groups, and campaigns via a static web panel on a VPS.

**Roles:** tenant user · admin (impersonation, subscriptions) · Celery/service (`INTERNAL_SERVICE_TOKEN`).

**Out of scope (confirmed in PROJECT_PLAN):** payment gateway, mobile app, SPA build, Kubernetes, desktop product.

---

## 2. Stack and architecture

| Layer | Technology |
|-------|------------|
| API / runtime | Python 3.12, FastAPI, uvicorn |
| Auth | JWT (PyJWT HS256), bcrypt passwords, token revoke + tenant token version |
| Vault | cryptography Fernet + PBKDF2HMAC (480k iters); per-tenant session crypto |
| SaaS DB | PostgreSQL 16 (`psycopg` + pool): tenants, users, subscriptions, revoked_tokens |
| Tenant ops DB | SQLite per tenant under `data/tenants/{id}/` |
| Cache / queue | Redis 7 (auth rate limit); optional Celery worker profile |
| Edge | Caddy 2 (TLS / Let's Encrypt) |
| Deploy | Docker Compose, GitHub Actions CI + SSH deploy |
| Tests | pytest (+ httpx), CI jobs: smoke, compose-config, e2e |
| Client lib | `maxapi-python` (unofficial MAX API) |

### Runtime shape

```
Browser → Caddy:443 → FastAPI (main.py + app/) → PG (SaaS)
                                         ↓         SQLite per tenant
                                    asyncio campaign workers
                                         ↓
                                    MAX API (unofficial)
Optional: Celery → POST /api/campaign/start (INTERNAL_SERVICE_TOKEN)
```

### Layout highlights

| Path | Role |
|------|------|
| `main.py` (~93 KB / ~2310 lines) | Remaining monolith: app wiring, some core/worker glue |
| `app/` | SaaS package: auth, tenant, vault, campaign_*, routes_*, db_pg, sqlite, middleware, subscriptions, monitor |
| `antiban_core.py` | Anti-ban / pacing primitives |
| `celery_worker.py` | Optional Celery entry |
| `static/` | `index.html`, `auth.html`, `admin.html` (no SPA build) |
| `migrations/` | SQL migrations (SaaS core, revoked tokens, tenant token version) |
| `scripts/` | deploy, verify, backup/restore, bootstrap-vps, gen-secrets, ensure-admin |
| `caddy/` | Caddyfile |
| `tests/` | 32 `test_*.py` files (auth, vault, tenant isolation, campaign, celery, e2e, …) |
| `tools/` | One-off refactor scripts for `main.py` extraction |
| `.github/workflows/` | `ci.yml`, `deploy.yml` |

---

## 3. Domains / modules

| Domain | Primary artifacts | Notes |
|--------|-------------------|-------|
| Auth / sessions | `app/auth.py`, `routes_auth.py`, `register.py`, `auth_rate_limit.py`, middleware | JWT cookie/Bearer; logout revoke; Redis rate limit |
| Tenant isolation | `app/tenant.py`, `paths.py`, `tenant_init.py`, `tenant_sqlite.py`, middleware ContextVar | Critical for multi-tenant safety |
| Vault / secrets | `app/vault.py`, `vault_store.py`, `routes_vault.py` | Encrypts MAX session material at rest |
| Campaign engine | `campaign_worker.py`, `campaign_send.py`, `campaign_pacing.py`, queue/store/runtime/query/facade | Per-tenant worker registry (ADR 001) |
| Anti-ban | `antiban_core.py`, pacing modules | Unofficial API risk surface |
| Admin | `routes_admin.py`, `static/admin.html` | Impersonation, subscription grant |
| Subscriptions | `subscription_jobs.py`, `db_pg` subscription helpers | Manual billing; lifecycle loop stops workers on expiry |
| Groups / profiles / messages | `routes_groups.py`, `routes_profiles.py`, `routes_messages.py`, `routes_settings.py` | Tenant SQLite |
| Monitoring | `routes_monitor.py`, `ops_monitor.py` | Health, Prometheus-ish metrics, Telegram alerts |
| Data access | `db_pg.py`, `sqlite_backend.py` | Hybrid PG + SQLite |
| Ops / deploy | Docker, Caddy, scripts, PRODUCTION-OPS | Production-ready runbook |

---

## 4. Documentation inventory

| Doc | Status |
|-----|--------|
| `README.md` | Present — deploy quickstart, env table |
| `docs/HOW-IT-WORKS.md` | Present — strong product/architecture narrative |
| `docs/PRODUCTION-OPS.md` | Present — deploy, Celery, backup, monitoring |
| `docs/PROJECT_PLAN.md` | Present — vision, milestones, risks, out-of-scope |
| `docs/adr/001–003` | Present — tenant workers, pacing, worker extraction |
| `docs/deps/`, `docs/lessons/` | **Absent** (Phase 2/3 optional — N/A for now) |

**Doc gaps (product-facing):**

- No API OpenAPI/export doc beyond FastAPI autodocs (if enabled in runtime).
- No dedicated security threat model doc (risks scattered in PROJECT_PLAN / HOW-IT-WORKS).
- `main.py` remaining ownership map vs extracted `app/` modules is not summarized.
- Billing explicitly manual — OK; should stay documented as out-of-scope for payment integrations.

---

## 5. Risk areas

| Area | Severity | Why |
|------|----------|-----|
| **Tenant isolation** | Critical | Cross-tenant data leak via wrong paths / lost ContextVar / admin impersonation bugs |
| **Vault / session crypto** | Critical | MAX session material; Fernet keys; volume backups contain secrets |
| **Auth / JWT / internal token** | High | Long-lived JWT (7d), `INTERNAL_SERVICE_TOKEN`, admin bootstrap secrets |
| **Unofficial MAX API / anti-ban** | High | Account bans; pacing/warmup must not be casually “optimized away” |
| **Hybrid PG + SQLite** | High | Backup must cover both; migration/consistency pitfalls |
| **Monolith `main.py`** | Medium | Large blast radius for edits; partial extraction (ADR 003) |
| **Subscriptions (manual)** | Medium | Gating campaign start; lifecycle jobs; no payment PCI surface today |
| **Deploy / secrets in `.env`** | Medium | Placeholder secrets, deploy key, Redis/PG passwords |
| **Celery optional path** | Medium | Dual execution paths (in-process vs Celery) need parity testing |
| **Static UI** | Low–Med | Large HTML files; XSS/CSRF considerations with cookie auth |

Payments/billing gateway: **N/A** (manual admin grant only).

---

## 6. Capability surface (for harness selection)

| Capability | Required? |
|------------|-----------|
| Architecture / runtime (FastAPI, asyncio workers) | Required |
| Languages / frameworks (Python) | Required |
| Domain: campaigns / queues / anti-ban | Required |
| Data / storage (Postgres + SQLite) | Required |
| Auth / JWT / multi-tenant | Required |
| Vault / secrets handling | Required |
| Integrations (MAX API, optional Telegram, Celery/Redis) | Required |
| Testing / quality (pytest, CI) | Required |
| Security / privacy | Required |
| UX / accessibility (static panel) | Light — UI polish not primary; avoid heavy frontend agent roster |
| Payments / billing | **N/A** (manual subscriptions) |
| Deployment / ops (Docker, Caddy, scripts) | Required |
| Admin / monitoring | Required |

---

## 7. Suggested mechanical commands

Useful project commands:

```bash
# Install
pip install -r requirements.txt -r requirements-server.txt
pip install -r requirements-dev.txt   # if present; else pytest httpx

# Unit / smoke
MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/ -q

# E2E (needs DATABASE_URL / local Postgres as in CI)
MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/test_e2e_server.py -q

# Compose validate (env vars required — see ci.yml)
docker compose config -q

# Local run (dev)
# uvicorn / run.bat — follow README; prefer Docker for full stack

# Deploy (VPS)
bash scripts/deploy.sh
bash scripts/verify_deploy.sh
bash scripts/backup-volumes.sh
```

CI source of truth: `.github/workflows/ci.yml` (`server-smoke`, `compose-config`, `server-e2e`).

---

## 8. Audit verdict

Mature production-oriented FastAPI SaaS with solid product docs (HOW-IT-WORKS, PRODUCTION-OPS, ADRs, PROJECT_PLAN) and meaningful test coverage around auth, vault, and tenant isolation. Architecture risk concentrates on **tenant isolation**, **vault/secrets**, **campaign/anti-ban**, and residual **`main.py` monolith**.
