# FINAL PRODUCTION READINESS AUDIT — MAX Sender / maxbot

**Date:** 2026-08-21  
**Auditor role:** independent Principal / Security / SRE / QA (this session)  
**Workspace:** repository root = server tree (`C:\Users\Admin\Documents\Projects\server`)  
**Method:** evidence from current runtime code, compose, CI, scripts, and tests. README / CURRENT_CONTEXT / DECISIONS / Feature reports / commit messages / prior Verifier PASS / pytest counts from PM files are treated as hypotheses only.

**Remediation update (2026-08-22):** fixed orphan-profile deletion, tenant-log
fail-closed behavior, per-thread SQLite connections, impersonation-token
revocation, atomic PostgreSQL restore, `.env` permissions, deploy readiness,
migration checksums, CI lockfile parity, non-root runtime containers, and SQLite
integrity triggers. A third remediation wave added maintenance-window hybrid
backups, immutable CI/action pins, a production Environment gate, and container
resource limits. Regression evidence is recorded after each wave below.
Final wave-3 regression: **248 passed, 19 skipped**; workflow/backup contracts:
**17 passed**; CI and Compose YAML parse successfully.
Wave 4 adds an automated `restore --yes` path, a shared-volume single-app
instance lock, and Starlette's recommended `httpx2` TestClient backend.
Wave-4 regression: **249 passed, 20 skipped** on Windows; the POSIX lock
contention test is intentionally deferred to Ubuntu CI. No warnings remain.
Wave 5 closes fail-open tenant lifecycle paths: registration defaults closed,
scheduler tenant discovery returns no work on PostgreSQL failure, internal
campaign calls require an active subscription, revoke stops workers immediately,
deleted runtimes are dropped, `.deleting` crash leftovers are reconciled, and
SQLite uses `synchronous=FULL`.
Wave-5 regression: **255 passed, 20 skipped**. The only initially failing
legacy unit test was updated to isolate the newly added subscription lookup;
the confirmed full rerun is green.

Parallel investigation agents used (parent synthesized independently): [Repo map](f1ebe5d9-714d-4ae2-846e-210a7d3c52e1), [Appsec](24ac7773-cb38-4291-8d84-58878e9af301), [Data/workers](fdd757ca-b4fd-4c7b-9e60-d7cccb4c93e7), [CI/deploy](44ea9d16-d79f-42fd-90d8-466f708811b0), [Git/secrets](e106b2fa-fe9b-48a2-8463-95376aa3e7ec).

Addendum after specialist handoffs (same session, still no product code changes): verified F-P1-06 / F-P1-07 / F-P1-08. [Appsec](24ac7773-cb38-4291-8d84-58878e9af301) also proposed registration-open and vault-key-on-volume as P1; those stay P2 / accepted ADR 006 (product + documented threat model). Rejected CI YAML dummy JWT strings and the HOW-IT-WORKS Russian placeholder as production secrets.

---

## 1. Executive Summary

**This repository cannot be safely declared production-ready today.**

Auth, cookie-only JWT, tenant SQLite path isolation, and service-token gating are real and mostly implemented in middleware. That is not the same as a safe production campaign + deploy + DR story.

Confirmed blockers fire on the production path: stop/deploy during send, SIGTERM vs lifespan, shared SQLite connection under the default worker pool, broken group-delete helper, `/api/log` fallback to a process-global buffer (cross-tenant read on SQLite error), CI not testing the image you ship, auto-deploy, hot hybrid backup.

**STATUS: NO-GO**

P0: 0  
P1: 8 (all production blockers)  
P2: 21  
P3: 14

---

## 2. Repository Architecture

### What this tree is

This workspace **is** the server product. `desktop/` is **absent**. `maxserverapp/` is **absent**. Git history shows a flatten to server-only (`5bc9836`). Runtime still contains desktop-mode branches (`ApiPinMiddleware` skipped when `MAX_SERVER_MODE=1`).

| Path | Role | Source of truth? |
|---|---|---|
| `app/` + `main.py` + `antiban_core.py` + `celery_worker.py` | Runtime | **Yes** |
| `static/` | Runtime UI (no build step) | **Yes** |
| `Dockerfile`, `docker-compose.yml`, `caddy/Caddyfile` | Production path | **Yes** |
| `schema_pg.sql`, `migrations/*.sql` | PG schema (applied by `db_pg.init_schema`) | **Yes** |
| `scripts/deploy.sh`, `backup-volumes.sh`, `restore-volumes.sh`, `verify_deploy.sh` | Ops path | **Yes** |
| `requirements.lock`, `requirements-server.lock` | Docker install | **Yes for images** |
| `requirements.txt`, `requirements-server.txt` | CI install | **Yes for CI — different from Docker** |
| `.github/workflows/ci.yml`, `deploy.yml` | CI/CD | **Yes** |
| `.env.example` | Operator template | Partial (defaults ≠ Python defaults) |
| `docs/` | Claims | **No** |
| `tests/` | Evidence, not production | Partial |

### Runtime vs tooling vs docs

- **Runtime:** FastAPI app (`python -m app.main`), per-tenant SQLite under `data/tenants/{id}/`, PostgreSQL SaaS meta, Redis (rate limit + optional Celery), Caddy TLS.
- **Tooling:** pytest and `scripts/gen-secrets.sh`.
- **Docs that contradict code:** `README.md` still describes `desktop/` + `server/` split; `docs/HOW-IT-WORKS.md` says each tenant has `messages/active.txt` as *its* pool — server `load_message_pool()` reads **global** SQLite.

### Dead / leftover paths

- Tenant `data/tenants/{id}/messages/` is created (`app/tenant_init.py`) but server send path ignores it.
- Password-vault files (`.app_salt` / `.app_vault`) are deleted if encountered (`app/vault.py`).
- `USE_CELERY` is never used to enqueue work from the app; Celery is an optional HTTP trigger worker with no in-repo producer.

---

## 3. Runtime Architecture

### Hybrid data plane (code, not docs)

Two different `DATABASE_URL` parsers:

- `app.config.DATABASE_URL` — raw env; used by `app/db_pg.py` (SaaS users/tenants/subscriptions/JWT revoke).
- `main._resolve_database_url()` — **returns empty unless `MAX_USE_DATABASE_URL=1`**. Compose does not set that flag. Therefore `main.DB_BACKEND` stays `"sqlite"` in production Docker even though Postgres is required for auth.

This is intentional hybrid, not a broken SQLite path. Health `db_backend` will report `sqlite`. Confusing, but `_conn()` is tenant SQLite.

### Boundaries

| Layer | Module | Notes |
|---|---|---|
| HTTP | `app/register.py` → `app/routes_*.py` | Thin routers; many call `main` |
| AuthZ | `app/middleware.py` `ServerAuthMiddleware` | Cookie JWT → ContextVar |
| Tenant paths | `app/tenant.py` `get_effective_data_dir` | ContextVar; never client `tenant_id` on user APIs |
| Workers | `app/campaign_runtime.py` `RuntimeRegistry` | Per-tenant asyncio runtime |
| God module | `main.py` (~2920 lines) | DB helpers, MAX client, vault glue, lifespan, rate limit, PIN |
| PG | `app/db_pg.py` | Pool max_size=10 |

### Coupling / lifecycle issues

- Circular-ish: `app/sqlite_backend.py` imports `main`; `app/runtime.py` re-exports `main`; routers import `app.runtime.main`.
- Global process state: `_auth_sessions`, `_login_tasks` (keyed by `(tenant_id, profile_id)` — **correct**), vault_store by data_dir — **correct**, `_session_cache` JWT validation TTL 30s, `_settings_cache`.
- Worker snapshot: `start_worker` captures `snapshot_context()` and restores inside the task (`app/campaign_worker.py` ~710–751). This is the actual isolation mechanism after middleware `clear_context()`.
- **Single app replica only.** Comment in `celery_worker.py`: campaign registry is process-local. Compose has one `app` service. Horizontal scale of `app` would double-send. Not tested as a product limit beyond a comment.

### Desktop/server independence

Independence is **N/A as a second distribution** (desktop removed). Residual: one codebase still implements local PIN/WS-pin/desktop data dir. Not a hidden import of a `desktop/` package. Documentation claiming a live `desktop/` tree is false.

---

## 4. Security Audit

### High-level

Request path for tenant APIs:

```
HTTP → Caddy (TLS, CSP, HSTS) → uvicorn
  → AuthRateLimitMiddleware (login/register/restore only)
  → ServerAuthMiddleware
       PUBLIC? → pass
       Bearer == INTERNAL_SERVICE_TOKEN + POST start|schedule? → X-Tenant-Id → set_context(admin, that tenant)
       else cookie max_token → decode JWT → cached_validate_token_session → set_context from claims
       USER_FORBIDDEN prefixes for role=user
       subscription check for role=user on start/schedule/retry/test
  → route handler → main._conn() → sqlite keyed by ContextVar data_dir
  → finally clear_context()
```

User JWT in `Authorization: Bearer` is **not** used for session auth. Bearer is only compared to `INTERNAL_SERVICE_TOKEN`. ADR 008 matches current middleware.

### Cookie flags (runtime)

`app/auth_cookies.py`: `httponly=True`, `samesite=lax`, `path=/`, `secure=_is_secure_request` (HTTPS or `X-Forwarded-Proto: https`).

Behind Caddy this should be Secure. SameSite=Lax is not Strict. CSRF on cookie-authenticated POST from a third-party site is largely mitigated by Lax (cookies not sent on cross-site POST). No CSRF token. Acceptable for a first-party SPA with cookie credentials, residual XSS+CSRF combo if inline JS is compromised.

### CSP

`caddy/Caddyfile`: `script-src 'self'` (good), `style-src 'self' 'unsafe-inline'` (residual). Inline styles can still help some XSS gadgets; scripts from this origin are the larger risk. Static JS is first-party.

### Findings preview

No P0 auth bypass found. P1 items are deploy/concurrency/supply-chain, not “Tenant A reads Tenant B SQLite via API” given current `_conn()` binding.

---

## 5. Authentication

### Login

`POST /api/auth/login` is PUBLIC_EXACT.  
ENTRY: `routes_auth.login` → `auth.authenticate` (bcrypt) → optional `init_tenant_db` → JWT in HttpOnly cookie.  
No JSON token in the response body (`_auth_json_response` returns `_session_payload` only). ADR 008 residual about JSON `"token"` is **stale**.

`remember_me` defaults **True** on `LoginIn` / `RegisterIn`. Persistent cookie Max-Age = `JWT_EXPIRE_HOURS * 3600`. Default `JWT_EXPIRE_HOURS=168` (7 days).

### Registration

Python default if env unset: **closed** (`REGISTRATION_OPEN` not in `1/true/yes` → 403).  
Compose / `.env.example`: **`REGISTRATION_OPEN=${REGISTRATION_OPEN:-1}`** — new production stacks from example **open registration**.

Register creates PG tenant+user in one transaction (`db_pg.register_tenant_user`), then `init_tenant_db`. Failure → `rollback_tenant_registration` (PG delete + rmtree). Tested in `tests/test_register_rollback.py` (skipif without PG).

### JWT

HS256, `jti`, `tv` (tenant token_version), `imp`, `exp`.  
`require_jwt_secret()` in `hooks.before_start()` refuses server mode without ≥32-char env secret. Compose requires `JWT_SECRET`. Module-level `JWT_SECRET = _JWT_ENV or secrets.token_hex(32)` is a footgun only if something encodes before `before_start`; production entry is `app.main.main()` which calls `before_start` first.

Logout: decode cookie → `revoke_token(jti)` → `invalidate_session_cache(jti)` → clear cookies.

`cached_validate_token_session`: 30s in-process TTL. Logout pops cache. Single uvicorn worker in compose → revoke is immediate in that process. A second app replica would have a 30s revoke delay (replicas are unsupported anyway).

### Restore / impersonation

`restore-session`: PUBLIC, cookie required, **rejects `imp=true`**.  
`exit-impersonation`: PUBLIC_EXACT (no user JWT required); authenticates **`max_admin_token` backup cookie**, restores it as `max_token`, session cookie (`remember_me=False`).  
Impersonation: admin-only, sets session `max_token` (imp JWT) + backup admin cookie. Middleware blocks `/api/admin` while `impersonating`.

### WebSocket

`/ws/` is a PUBLIC_PREFIX (middleware skips JWT). Handler `ws_status` `accept()` then `_authenticate_ws`: first message must be `{type:auth}` within 5s; **server mode uses cookie only** (JSON token ignored). Revalidate every 30 ticks via `cached_validate_token_session`. Desktop PIN path unused in server mode.

Unauthenticated TCP/WS accept before auth: connection DoS / slowloris class, not data leak if auth fails closed (close 4401).

### INTERNAL_SERVICE_TOKEN

Empty token does not authenticate (`bool(internal and bearer == internal)`).  
Valid token + POST `/api/campaign/start` or `/schedule` requires numeric `X-Tenant-Id` and existing tenant. Context: `role=admin`. **Subscription middleware check is `role == "user"` only — service token bypasses subscription.** Celery is default-off; if enabled, unpaid tenant campaigns can be started. Metrics also use this token (`/metrics`).

### API PIN

`ApiPinMiddleware` **returns immediately in server mode**. PIN is desktop leftover. `static/js/index.js` still has `localStorage maxApiPin` / Bearer pin for non-server. Server UI uses `credentials: 'include'` (`static/js/auth.js`).

---

## 6. Authorization

Cabinet (`role=user`, not impersonating):

Forbidden prefixes (`ServerAuthMiddleware.USER_FORBIDDEN`): `/api/settings`, `/api/messages`, `/api/campaign/pause`, `/reset`, `/test`, `/schedule`, `/retry_failed`.

Allowed: groups, profiles (proxy patch 403 for cabinet), campaign start/stop, dashboard, send_log (proxy/sent_text redacted), vault status (auto-unlock).

Admin without tenant_id cannot hit tenant panel APIs except listed global prefixes.

Impersonating admin keeps `role=admin` so USER_FORBIDDEN does not apply — intended ops.

`_require_admin()` on admin routes is defense-in-depth (middleware already gates `/api/admin`).

Vertical escalation: user JWT cannot become admin without PG `role`. Horizontal: tenant_id comes from JWT claims, not body. Admin can impersonate any tenant (by design, logged).

---

## 7. Tenant Isolation

Tenant id for AuthZ: **JWT `tenant_id` / ContextVar**, not request body (except service-token `X-Tenant-Id`, which is a privileged internal API).

SQLite: `get_effective_data_dir` → `data/tenants/{id}/` or `data/global` for admin settings/messages.

### Exploit scenarios (mental, against current code)

| Attack | Result |
|---|---|
| Tenant A GET Tenant B profiles by ID | Hits A's SQLite; 404. Profile IDs are per-DB. |
| Tenant A GET `/api/log` while A's SQLite errors | **Leaks `main._log` (F-P1-08)** |
| Tenant A mutate Tenant B group | Hits A's SQLite; 404. |
| Tenant A DELETE `/api/admin/users/{B}` | 403 (`role != admin`). Covered by `test_cross_tenant_api.py`. |
| Tenant A start Tenant B campaign | Start uses A's context/registry key. Cannot select B. |
| Tenant A read B vault/session files | Paths from context data_dir. No path param for tenant root. |
| Tenant A `X-Tenant-Id: B` without service token | Ignored; cookie tenant used. |
| Stolen service token + `X-Tenant-Id` | **Can start B's campaign** (privileged). |
| Worker after request ends | Snapshot restored in worker task. |
| Admin impersonate | Yes, by design; restore-session rejects imp cookies. |

### Weak evidence

`test_cross_tenant_api.py` registers two tenants and checks **empty** profile lists + admin 403. It does **not** insert rows in A and try B's cookie against A's IDs. Isolation is structural (separate files) more than tested IDOR.

### Worker / background

- Scheduler iterates `list_tenants_with_users()` then `tenant_scope(tenant_id=tid)`.
- On PG exception, `scheduler_tenant_ids()` returns `[None]` → `_conn()` uses `ROOT/data` (legacy), not a random tenant. Wrong DB, not Tenant B's DB. P2.
- Startup `_try_auto_resume` runs with `tenant_id is None` (lifespan assert). Multi-tenant resume depends on scheduler (~15s), not startup. P2.
- Tenant delete: `stop_worker` → bump `token_version` → quarantine dir `{id}.deleting` → PG delete → purge. PG fail restores files. Residual leftover `{id}.deleting` if crash mid-swap.

### Message pool (docs lie)

Server `load_message_pool()` / `save_messages_file()` use `_global_conn()`. All tenants send the **admin global** pool. Not a cross-tenant data leak; it is shared copy. HOW-IT-WORKS per-tenant `messages/active.txt` is false.

---

## 8. Database

### PostgreSQL

- Pool: `psycopg_pool` min 1 max 10, timeout 30s, max_waiting 50.
- Bootstrap: `schema_pg.sql` (only `schema_migrations`) mounted into Postgres initdb; **SaaS DDL is applied by the app** (`init_schema` + `migrations/001–003`).
- FKs: tenants ← users/subscriptions ON DELETE CASCADE. `impersonation_log.target_tenant_id` has **no ON DELETE CASCADE**; `delete_tenant` deletes log rows first. `granted_by` has no ON DELETE SET NULL (admin user is not deleted with a tenant).
- `token_version` on tenants (003).
- `revoked_tokens` (002).
- No automated down-migrations (`migrations/README.md`).

### SQLite (per tenant)

- WAL, `foreign_keys=ON`, `synchronous=NORMAL` (can lose last frames on crash).
- Connection cache `_tenant_db_conns` keyed by data_dir string under a lock.
- Tenant ops are **not** in the same transaction as PG. Register: PG commit then filesystem init; rollback helper exists. Campaign send: SQLite only.

### PG commit → SQLite → worker failure

- Subscription grant: PG only. Worker reads `subscription_active` on HTTP start and on scheduler/auto-resume. In-flight worker **does not** re-check subscription every send. Revoke mid-campaign: worker continues until stop/scheduler tick. P2.
- Tenant delete: worker stop first (best-effort), then files, then PG. In-flight `send_message` can still complete (see campaign findings).
- Admin message upload resets **all tenant** queue indices (`_reset_all_tenants_queue_for_new_pool`) while campaigns may be running. P2.

---

## 9. Vault / Secrets / Sessions

### Secrets inventory (no values)

| Secret | Where | Access |
|---|---|---|
| `JWT_SECRET` | env / `.env` (gitignored) | App process |
| `ADMIN_PASSWORD` | env; hashed into PG on first boot if no admin | App + PG |
| `INTERNAL_SERVICE_TOKEN` | env | App + optional Celery |
| `POSTGRES_PASSWORD`, `REDIS_PASSWORD` | env | Compose |
| Per-tenant `.app_key` | `data/tenants/{id}/.app_key` on `max_server_data` volume | App; **also inside backups** |
| Fernet session blobs | `sessions/{profile_id}/session.db.enc` | Same volume |
| MAX session plaintext | ephemeral `session.db` while unlocked/sending | Disk while live |

`.env.example` contains `change-me*` placeholders only. `hooks.before_start` `require_production_secrets()` rejects empty/`change-me*` unless `MAX_TEST=1`. `scripts/deploy.sh` also rejects placeholders.

### Crypto model (ADR 006 — matches code)

`ensure_vault_unlocked`: generate/load raw Fernet key from `.app_key`, cache per `data_dir` in `vault_store`. Password vault APIs return **410** in server mode.

**Volume theft or backup theft ≡ session theft.** Encryption-at-rest does not protect `max_server_data` or `backups/*/data.tar.gz`. This is an accepted architectural choice, not a missed lock. Treat as **accepted risk** only if VPS disk, Docker volume, and `./backups` are as protected as production session cookies. Otherwise it is a P1 ops failure waiting to happen — classified as accepted with conditions, not a code defect.

Key rotation: `reencrypt_all_sessions` exists; no production rotation runbook in scripts.

Process-global `_fernet` on the hot path was the ADR 006 bug; current encrypt/decrypt goes through `app.vault` + `_resolve_data_dir()`. Tests: `test_vault_hot_path_isolation.py`, `test_vault_per_tenant.py`.

---

## 10. Campaign / Workers

### Lifecycle (code)

- Start: vault check, global message pool, groups/profiles, preflight proxies, `auto_run=1`, `start_worker` (one task per tenant, `worker_lock` prevents double start).
- Stop/pause: `auto_run=0`, cancel supervisor + pool tasks, `finish_campaign`.
- Pause is stop with status `paused`; progress indices kept (`test_campaign_auto_run.py`).
- Reset refused while worker busy.
- In-flight group lock + `claim_lock` per runtime (`test_inflight_groups.py`).
- Ban path can stop worker (`test_ban_detection.py`).
- Restart: `_reset_auth_on_startup` marks `campaigns.status='running'` → stopped, `queue_state.running=0`. `auto_run` setting can still resume via scheduler.

### Celery / Redis

- Default `USE_CELERY=0`. App never calls `enqueue_campaign_start.delay`.
- Celery worker POSTs to `http://{MAX_HOST}:{MAX_PORT}/api/campaign/start` with service token. Compose sets `MAX_HOST=app`.
- Redis: rate limit; fail-open to in-memory limiter if Redis ping fails (`auth_rate_limit.py`). Single replica → OK. Redis down does not stop campaigns.

### Confirmed races (P1)

**Duplicate send on cancel after MAX success, before SQLite persist.**

`send_with_retry` (`app/campaign_send.py`): `await c.send_message(...)` then, separately, INSERT `send_log` status=sent. `CancelledError` is `BaseException` (Python 3.9+), not caught by `except Exception`. Pool worker (`campaign_worker.py` ~428–430) on cancel **returns the message to the bag** and re-raises.

Timeline:

1. MAX accepts the message.  
2. Task cancelled (user stop, watchdog restart, deploy).  
3. No `send_log` row. Bag gets the index back.  
4. Next start/auto-resume sends the same text again.

Not covered by a regression test. This is a production campaign defect, not a docs issue.

**SIGTERM handler vs lifespan.**

`app/main.py` signal handler: set `shutting_down`, `_encrypt_all_sessions()`, `sys.exit(0)` — **does not** `stop_all_workers`. FastAPI `lifespan` finally **does** stop workers then encrypt. Docker `stop` delivers SIGTERM to PID 1 (`python -m app.main`). The custom handler can fire and hard-exit while workers still send, and encrypt session files under a live client.

Deploy / container restart during an active campaign is therefore unsafe.

Watchdog restart of a stuck worker also cancel+maybe auto_run start — same duplicate-send window.

---

## 11. API

Inventory (server mode). Auth = cookie JWT unless noted.

| METHOD | PATH | AUTH | ROLE | TENANT | Side effect | Rate limit | Risk |
|---|---|---|---|---|---|---|---|
| GET | `/`, `/auth.html`, `/admin.html` | public | — | — | none | IP 180/min on `/api` only | HTML public; API still gated |
| GET | `/static/*` | public | — | — | none | — | first-party JS |
| GET | `/api/health` | public (limited body) | — | — | none | excluded | leaks `db_ok` |
| GET | `/metrics` | service token | — | global | none | — | token = campaign-start token |
| WS | `/ws/status` | cookie after accept | any authed | JWT | status stream | — | accept-before-auth |
| POST | `/api/auth/register` | public | — | new | PG+SQLite | auth RL | open if compose default |
| POST | `/api/auth/login` | public | — | user's | cookie | auth RL | brute-force limited |
| POST | `/api/auth/restore-session` | cookie | — | — | none | auth RL | rejects imp |
| POST | `/api/auth/exit-impersonation` | admin backup cookie | admin | — | cookie swap | — | |
| POST | `/api/auth/logout` | cookie | — | — | revoke jti | mutation 60/min | |
| GET | `/api/auth/me` | cookie | — | ctx | none | — | |
| GET/POST | `/api/vault/*` | cookie | user/admin | ctx | 410 on setup/unlock/lock in server | mutation | status ok |
| CRUD | `/api/profiles*` | cookie | user+ | ctx SQLite | MAX login | mutation | cabinet proxy 403 |
| CRUD | `/api/groups*` | cookie | user+ | ctx | proxy 403 cabinet | mutation | |
| GET/POST | `/api/messages*` | cookie | **not user** | **global** | rewrite pool + reset all tenant queues | mutation | |
| GET/PUT | `/api/settings*` | cookie | **not user** | global if admin | pacing copy to tenants | mutation | webhook URL SSRF as admin |
| POST | `/api/campaign/start` | cookie **or** service+X-Tenant-Id | user needs sub | ctx | start worker | mutation | service skips sub |
| POST | `/api/campaign/stop` | cookie | user+ | ctx | stop | mutation | cancel race |
| POST | `/api/campaign/pause\|reset\|schedule\|retry\|test` | cookie | **not user** (except start/stop) | ctx | | mutation | |
| GET | `/api/campaigns` | cookie | user+ | ctx | none | — | |
| GET | `/api/dashboard`, `/api/send_log` | cookie | user+ | ctx | none | — | redaction |
| GET | `/api/log` | cookie | user+ | ctx **or global `_log` on error** | none | — | **F-P1-08** |
| POST/GET | `/api/backup`, `/api/backups` | cookie | user+ | ctx | copy tenant `app.db` | mutation | local SQLite snapshots, not volume DR |
| `/api/admin/*` | cookie | admin, not imp | path tenant_id | PG+SQLite | mutation | IDOR blocked by role |

No CORS middleware (same-origin cookie app). Uploads capped `MAX_UPLOAD_BYTES=5MiB`. SQL in tenant DBs uses placeholders. `send_log` search concatenates `LIKE` with bound params.

Admin `webhook_url` → `http_post_json` (urllib). Admin-triggered SSRF. No allowlist. P3 given admin trust.

---

## 12. Backup / Restore

### What is backed up

`scripts/backup-volumes.sh`:

1. `pg_dump -Fc` of live Postgres (hot).  
2. Best-effort WAL checkpoint of every `/app/data/**/app.db` inside **running** app.  
3. `tar czf` of live `/app/data` via `docker compose run ... tar` (second app container sharing the volume).  
4. Verify: non-empty dump, magic `PGDMP`, `gzip -t`, `tar -tzf` non-empty. **No SHA256 of payload. No app version recorded.**

`umask 077` + `chmod 700` on dest. Archive **contains `.app_key` + ciphertext**.

### Snapshot semantics

**HOT BACKUP ≠ CONSISTENT SNAPSHOT.**

- PG dump and data tar are sequential, not a filesystem freeze / `pg_backup_start` + volume snapshot.  
- Writes continue during dump and during tar. Checkpoint then tar still races new WAL.  
- PG SaaS rows can disagree with tenant directories (tenant registered during the window).

Tests (`tests/test_backup_scripts.py`) **grep the script source**. They do not restore a live stack. NOT a production-equivalent DR test.

### Restore

`scripts/restore-volumes.sh`:

- Interactive `read` confirmation — cannot be used unattended / from CI.  
- Extract to `.incoming-restore`, swap live children to `.outgoing-restore`, then `pg_restore --clean --exit-on-error`.  
- PG fail → rollback data from `.outgoing-restore`.  
- Leftover `.outgoing-restore` blocks retry.  
- Interrupted restore after swap and before PG: documented leftover; not automatically healed.  
- Disk full: not handled beyond `set -e`.  
- Then `docker compose up -d` + `verify_deploy.sh`.

In-app `POST /api/backup` is **tenant SQLite file copy** into `data/tenants/{id}/backups/`, not the hybrid volume backup.

**Verdict: PARTIAL.** You can probably get a VPS back if the archive is intact and you run restore by hand. You cannot honestly claim atomic hybrid recovery or automated DR.

---

## 13. Docker / Deployment

### Compose (`docker-compose.yml`)

- App built from local Dockerfile; sidecars **digest-pinned** (redis/caddy/postgres alpine). App image itself is not registry-pinned (built in place).  
- Secrets via required env (`:?`).  
- `REGISTRATION_OPEN` defaults **1**.  
- **No `mem_limit` / CPU limits / ulimits / pids limit.**  
- App `expose` 8765 only (not published) — good; Caddy is the edge.  
- Healthcheck requires `db_ok`. Caddy `depends_on: app healthy`.  
- `restart: unless-stopped`.  
- Redis healthcheck passes password on argv (process list). P3.  
- Postgres initdb only gets `schema_pg.sql` (migrations table). App applies 001–003.

### Dockerfile

- `python:3.12-slim@sha256:...` pinned.  
- `pip install -r requirements.lock` and `requirements-server.lock`.  
- Lockfiles **generated with pip-compile on Python 3.11** (header comment). Image is 3.12. Possible wheel/ABI drift.

### Deploy

`scripts/deploy.sh`: placeholder check, backup if PG volume exists, compose up, `verify_deploy.sh`.  
`.github/workflows/deploy.yml`: **on successful CI `workflow_run` to main/master, SSH and deploy that SHA automatically.** `concurrency` does not cancel in-progress. Deploy job `verify` runs `pytest tests/` **without `DATABASE_URL`** — skipif PG modules skip. `CHECK_HTTPS=0`. Legacy `server/.env` copy remains.

Halfway deploy: compose up is not transactional. Backup exists only if PG volume already present. Rollback = git checkout previous SHA + compose up; data rollback is a separate restore. New image + old DB: forward-only SQL migrations; no down scripts.

### Failure models

| Event | Actual |
|---|---|
| Deploy fails after backup, before healthy | Old containers may be replaced; restore from last backup dir |
| Container restart | lifespan startup resets running campaigns; auto_run may resume |
| Postgres down | Auth/APIs using PG fail; in-flight SQLite workers continue |
| Redis down | Rate limit memory fallback; Celery broken if used |
| Disk full | SQLite/backup fail; not tested |
| Old image rollback | Code rolls back; schema 001–003 stay applied |

---

## 14. Dependencies

| Consumer | Installs |
|---|---|
| Docker | `requirements.lock` + `requirements-server.lock` (pinned) |
| CI `server-smoke` / `server-e2e` / deploy `verify` | `requirements.txt` + `requirements-server.txt` (**ranges**: `fastapi>=0.115`, `cryptography>=43`, `celery>=5.4`, …) + extra `pytest httpx` |
| Decision G-4 | Explicitly accepts this split |

**Reproducibility: FAIL.** CI does not test the exact graph production runs. Lockfile Python 3.11 vs Docker 3.12 adds a second drift axis. No git URL deps in requirements. `maxapi-python==2.4.0` is pinned in the loose file (good for a past MAX handshake break).

This audit did not run `pip-audit` / OSV against the lockfile (no network vulnerability scan in-session). Treat known-CVE status as **NOT VERIFIED**.

---

## 15. CI/CD

### `ci.yml`

| Job | Trigger | Deps | Tests |
|---|---|---|---|
| `server-smoke` | push PR main/master | loose requirements | `pytest tests/` without DATABASE_URL, then listed PG modules with DATABASE_URL, then e2e |
| `compose-config` | same | none | `docker compose config -q` |
| `server-e2e` | same | loose | `test_e2e_server.py` with PG |

Postgres **service image is `postgres:16-alpine` unpinned** (compose production is digest-pinned).

CI **does** run skipif modules in a second process (cannot silently skip if DATABASE_URL is set). Historical commit `489e8fd` (“gate smoke Postgres on e2e only so deploy can proceed”) shows a prior weakening; current file re-includes PG modules in smoke.

### `deploy.yml`

Auto-production on green CI. Permissions default (contents). Secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PATH`. If those GitHub secrets exist, **every merge deploys**. No environment approval, no staging, no HTTPS check.

GREEN CI ≠ GREEN PRODUCT: no Docker image test, no backup/restore execution, no campaign concurrency under load, skipif still skip in deploy-verify job.

---

## 16. Test Quality

**This audit did not execute pytest.** Counts in CURRENT_CONTEXT (“231 passed, 26 skipped”) are **untrusted**.

### Inventory

56 files matching `tests/test_*.py`.

**Skip / skipif (code):**

| Mechanism | Files | Meaning |
|---|---|---|
| `requires_postgres` skipif | `test_cross_tenant_api`, `test_e2e_server`, `test_register_rollback`, `test_admin_impersonation_campaign`, `test_db_pg_helpers`, `test_auth_remember_me` | **SKIPPED** unless DATABASE_URL + psycopg in that process |
| `pytest.importorskip("celery")` | `test_celery_worker.py`, part of `test_phase3_tenant_scope.py` | SKIPPED if celery not installed (CI installs requirements-server so likely run) |
| `importorskip("pymax")` | `test_cloud_password.py` | may skip |

### Domain coverage

| Domain | Unit | Integration | E2E | Negative | Concurrency | Failure | Prod-equivalent |
|---|---|---|---|---|---|---|---|
| AUTH | cookies, revoke, rate limit | remember-me (PG) | login/admin in e2e | 401/403 | no | secrets placeholder | PARTIAL |
| TENANT | paths, sqlite isolation | cross-tenant empty lists | e2e 403 admin | 403 | worker registry | delete quarantine | PARTIAL |
| VAULT | encrypt, per-dir | hot-path | no | InvalidToken | no | empty db | PARTIAL |
| CAMPAIGN | pacing, inflight, auto_run | mocked send | no live MAX | ban/flood | inflight lock | no cancel-after-send | **FAIL** for stop/deploy |
| DATABASE | pool helpers | PG skipif | — | — | no | — | PARTIAL |
| BACKUP | **script string asserts** | no | no | gzip magic | no | no live restore | **FAIL** |
| DEPLOY | compose strings in tests | compose-config job | verify_deploy not in CI | — | — | — | PARTIAL |
| API | authz review tests | TestClient | e2e subset | 403 | no | — | PARTIAL |
| UI | static string tests | no browser | no | — | — | — | PARTIAL |

### Deleted / weakened tests

- `tests/test_dashboard_message_pool.py` **deleted** (`e91e11a` “keep dashboard resilience without flaky smoke test”; `db0b292` “drop flaky async dashboard tenant test”). Per audit rule: **NOT VERIFIED**, not closed.  
- Historical smoke tests (`test_smoke_vault.py`, pause/resume, health, onboarding) deleted in desktop/server split — desktop gone; server replacements exist only in part.

Mocks: campaign send success is mocked in several tests (CURRENT_CONTEXT claims this). Live unofficial MAX API is **NOT TESTED** in CI (expected, but then production send path is unverified).

---

## 17. Security Regression

Last ~40 commits include real runtime fixes (cookie-only JWT, cabinet proxy 403, vault 410, internal token + X-Tenant-Id, backup via app image, no SMS on send, maxapi pin). This audit checked **current code**, not messages.

| Topic | In runtime now? | Regression test? | Old exploit? |
|---|---|---|---|
| Cookie-only user JWT | Yes (`middleware.py` cookie, not Bearer user JWT) | unit + e2e cookies | Bearer user JWT ignored |
| Restore rejects impersonation | Yes | e2e / auth routes | restore with imp cookie 401 |
| Cabinet proxy | 403 `is_cabinet_user` | `test_review_fix_authz.py` / group proxy tests | PATCH proxy as user 403 |
| Metrics auth | service token only | `test_security_tail.py` | user JWT 401 |
| Cross-tenant admin | 403 | `test_cross_tenant_api.py` | user cannot delete other tenant |
| Duplicate send on cancel | **Unfixed** | **No** | **Still possible** |
| SIGTERM vs workers | **Unfixed** | shutdown test only checks attribute names | **Still possible** |
| Flaky dashboard test | deleted | no replacement file | dashboard empty-tenant path weakly tested |

No in-session git-history secret dump (tooling blocked history search for secret-bearing paths). **Historical leak status: NOT VERIFIED.** Current tree: `.env` gitignored; example placeholders only.

---

## 18. Documentation Consistency

| Claim | Reality |
|---|---|
| `desktop/` exists | **Absent** |
| Canonical `maxserverapp/` | **Absent**; leftover in rules/DECISIONS/CORE-SYNC |
| Per-tenant `messages/active.txt` is the send pool | **Global** `message_pool` table |
| JSON login returns `token` (ADR 008 residual) | **Does not** |
| WS JSON token fallback (ADR 008) | Server WS **cookie only** |
| ADR 001 “WS uses JWT `?token=`” | **Stale**; cookie after `{type:auth}` |
| FEATURE * COMPLETE + Verifier PASS | Untrusted; residuals still in code |
| Pytest 231/26 | Untrusted this session |
| Registration fail-closed | Python unset=closed; **compose default open** |
| Celery campaign queue | Trigger-only, **no producer** in app |
| G-4 lockfile CI | Still true; still a prod risk |

---

## 20. Reliability / Performance

- Blocking: `http_post_json` / Telegram via `asyncio.to_thread` in places; SQLite claims use `to_thread` for claim sync body. MAX client awaits. God-module still has sync disk/SQLite on the event loop in many routes (`with m._conn()` in async handlers). Fine at tens of tenants; **not characterized at 100–1000**.  
- PG pool max 10; one process.  
- `RATE_LIMIT=180` / 60s per IP on `/api` plus 60 mutations/min per user.  
- Unbounded: `_log` fallback, `_session_cache` (grows with distinct `jti` until TTL — dict not pruned of expired keys except overwrite). P3 leak of cache keys.  
- Worker registry grows with tenants that ever started a worker; not bounded.  
- Scheduler O(tenants) every 15s. ADR 001 admits this.  
- No compose resource limits → one noisy tenant / runaway pool can OOM the VPS.  
- Global message pool + `_reset_all_tenants_queue_for_new_pool` is a cross-tenant **availability** coupling (not data leak).

---

## 21. Failure Matrix

| Failure | Expected | Actual (code) | Tested? | Severity |
|---|---|---|---|---|
| PostgreSQL down | Auth fail; health db_ok false | Yes; in-flight SQLite workers continue; scheduler may use tenant_id None | health unit-ish | P1 ops |
| Redis down | Degrade rate limit | Memory fallback; Celery dead | `test_auth_rate_limit_redis.py` partial | P2 |
| Worker crash (task) | Stop campaign, no duplicate | Cancel path can duplicate send | **No** | P1 |
| App crash / OOM | Docker restart; campaigns marked stopped; auto_run may resume | Yes | **No** live | P1 |
| Disk full | Fail closed | Unspecified | **No** | P1 untested |
| Backup corruption | Detect | gzip/tar/PGDMP checks; no checksum of contents | script grep | P1 DR |
| Restore interruption | Rollback | Leftover `.outgoing-restore`; interactive | grep only | P1 DR |
| Invalid JWT | 401 | Yes | yes | OK |
| Expired JWT | 401 | PyJWTError → 401 | yes | OK |
| Stolen cookie | Session until expiry/revoke | 7-day remember default; logout revokes jti | partial | P2 |
| Tenant spoof body | Ignore | JWT context | weak IDOR tests | OK arch |
| Impersonation restore | Reject | 401 | yes | OK |
| MAX API failure | retry then fail log | yes | mocked | PARTIAL |
| Flood wait | sleep parsed seconds | `antiban_core.flood_wait_seconds` | `test_flood_wait.py` | OK |
| Account ban | status banned, stop | yes | `test_ban_detection.py` | OK |
| Stop during send | no duplicate | **duplicate possible** | **No** | P1 |
| Deploy during campaign | drain then encrypt | SIGTERM may encrypt+exit live workers | **No** | P1 |
| Duplicate Celery task | idempotent start | `start_worker` lock returns if busy; HTTP double-start from two celery workers still one process lock | unit lock | P2 |
| Concurrent tenant delete | stop then purge | race with in-flight send | quarantine tests | P1 adjacent |
| Stolen volume/backup | sessions unreadable | **readable** (`.app_key` adjacent) | threat model documented | Accepted if ops OK |

---

## 22. Findings

### P0 — none confirmed

No demonstrated unauthenticated tenant-data read/write, JWT-none alg, or user→admin escalation in current request code.

---

### P1

#### F-P1-01 Duplicate send after cancel  
**Category:** Campaign / concurrency  
**Location:** `app/campaign_send.py` `send_with_retry` (send then persist); `app/campaign_worker.py` ~428–430 (`CancelledError` → `_return_to_message_bag`)  
**Evidence:** `await c.send_message` is not in the same critical section as `INSERT send_log ... 'sent'`. `CancelledError` is not `Exception`.  
**Impact:** Recipients get duplicate MAX messages; ban risk; incorrect send_log.  
**Scenario:** Operator clicks Stop, watchdog restarts, or deploy SIGTERM during send.  
**Root cause:** Cancel treated as “not sent”; MAX already accepted.  
**Fix:** Persist-or-ack before allowing bag return; on cancel after send, do not requeue; ideally mark sent in SQLite before or in the same task-local flag that cancel checks.  
**Regression test required?** Yes — fake client delays between send and DB write, cancel, assert bag/log.  
**Production blocker?** Yes.

#### F-P1-02 SIGTERM encrypt+exit skips worker drain  
**Category:** Deploy / worker lifecycle  
**Location:** `app/main.py` `_handle_signal` lines 35–42 vs `main.py` `lifespan` finally ~2806–2823  
**Evidence:** Handler calls `_encrypt_all_sessions()` and `sys.exit(0)` without `stop_all_workers`.  
**Impact:** Kill in-flight sends; encrypt session files while client may still use them; duplicates on auto_run resume.  
**Scenario:** `docker compose up` rolling replace, `deploy.sh`, host reboot.  
**Root cause:** Duplicate shutdown paths.  
**Fix:** Signal should set `shutting_down` and let uvicorn lifespan drain; or handler must `stop_all_workers` then encrypt.  
**Regression test required?** Yes (signal/lifespan order).  
**Production blocker?** Yes.

#### F-P1-03 CI does not install production lockfiles  
**Category:** Supply chain  
**Location:** `.github/workflows/ci.yml` install steps; `Dockerfile` COPY lockfiles; `requirements.lock` header “Python 3.11”; image 3.12  
**Evidence:** CI `pip install -r requirements.txt -r requirements-server.txt`; Docker `pip install -r requirements.lock`. DECISIONS.md G-4 admits this.  
**Impact:** Tests can pass on a different FastAPI/cryptography/celery than production.  
**Fix:** CI `pip install -r requirements.lock -r requirements-server.lock`; regenerate lockfiles with 3.12.  
**Regression test required?** CI job that diffs `pip freeze` vs lockfile.  
**Production blocker?** Yes for “we tested what we ship.”

#### F-P1-04 Automatic production deploy + weak deploy-verify  
**Category:** CI/CD  
**Location:** `.github/workflows/deploy.yml` `on.workflow_run` + SSH script; verify job `pytest tests/` without DATABASE_URL  
**Evidence:** Deploy if CI conclusion success; no GitHub `environment` protection; `CHECK_HTTPS=0`; PG skipif modules skip in verify.  
**Impact:** Merge to main ships to VPS; broken PG-path can still deploy if smoke’s second step was skipped or misunderstood; no human gate.  
**Fix:** Require `workflow_dispatch` and/or environment approval; run lockfile + PG tests in verify; keep HTTPS check on.  
**Regression test required?** Workflow policy test / documented gate.  
**Production blocker?** Yes until auto-deploy is disabled or gated.

#### F-P1-05 Hybrid backup is hot, not a consistent snapshot  
**Category:** DR  
**Location:** `scripts/backup-volumes.sh` sequential `pg_dump` then live `tar` of `/app/data`  
**Evidence:** No `fsfreeze`, no `pg_backup_start`, no single atomic snapshot. Tests only assert script text. Restore is interactive. Archives include vault keys.  
**Impact:** Restore can mix SaaS rows with a different generation of tenant files; false confidence in DR.  
**Fix:** Document RPO honestly **and** add a maintenance-window backup (stop app, dump, tar) or volume snapshot; checksums; non-interactive restore for disaster; execute restore in CI against compose.  
**Regression test required?** Yes — real compose backup/restore.  
**Production blocker?** Yes if you need reliable hybrid restore. Do not ship claiming atomic DR.

#### F-P1-06 Shared SQLite connection used from event loop and `to_thread`  
**Category:** Database / concurrency  
**Location:** `app/sqlite_backend.py` `_sqlite_connect` (`check_same_thread=False`); `_conn()` lock only covers dict lookup; `app/campaign_worker.py` `claim_next_job` uses `asyncio.to_thread(_claim_next_job_sync)` while `send_with_retry` writes on the same `Connection` from the loop  
**Evidence:** Compose default `WORKER_POOL_SIZE:-4`. sqlite3 docs require serialized access if one connection is shared across threads; this code does not serialize queries.  
**Impact:** Undefined behavior, lost updates, or tenant `app.db` corruption under the **default** pool size — not an optional scale path.  
**Scenario:** Two pool workers: one claiming in a thread, another inserting `send_log` on the loop.  
**Root cause:** One cached connection per data_dir, lock released before SQL.  
**Fix:** Per-tenant `threading.Lock` around all use of that connection, or one connection per thread, or stop using `to_thread` on the shared conn.  
**Regression test required?** Yes — concurrent claim+send against one tenant DB.  
**Production blocker?** Yes while pool size > 1 (production default).

#### F-P1-07 `_delete_profile_if_orphan` is called but never defined  
**Category:** API / cabinet  
**Location:** `app/routes_groups.py` lines 300 and 319; **no `def _delete_profile_if_orphan` in the repository** (grep: only those two call sites)  
**Evidence:** `DELETE /api/groups/{id}` and `DELETE /api/groups/{id}/profiles/{pid}` commit SQLite deletes, then `m._delete_profile_if_orphan(...)` → `AttributeError` → 500. No test covers these routes. Cabinet is allowed to create/delete groups.  
**Impact:** Group delete always fails after the row is already gone; orphan profiles/session dirs remain; operator retries.  
**Scenario:** Tenant user deletes a group in the cabinet.  
**Root cause:** Helper never landed (or was dropped) while call sites remained.  
**Fix:** Implement orphan cleanup (delete profile + session files if no remaining `group_profiles`) or remove the calls and document leftover profiles.  
**Regression test required?** Yes — delete last group membership, assert profile/session handling and 200.  
**Production blocker?** Yes for cabinet group lifecycle.

#### F-P1-08 `GET /api/log` falls back to a process-global buffer  
**Category:** Tenant isolation  
**Location:** `app/routes_dashboard.py` `get_log` 44–54; `main.py` `append_log` 490–497 always appends to `_log` (last 500 lines, all tenants)  
**Evidence:** Server path queries tenant `app_log`; `except Exception: pass` then `return {"lines": m._log[-200:]}`. Any authenticated cabinet user.  
**Impact:** On SQLite error (lock, disk full, quarantine race) Tenant A receives up to 200 log lines that may include other tenants’ phones, group names, bans, admin actions.  
**Scenario:** Disk full or WAL lock → `GET /api/log`. This is the only confirmed HTTP cross-tenant **read** in the tree.  
**Root cause:** Desktop fallback left in server mode; `_log` is not tenant-keyed.  
**Fix:** In server mode return `{"lines": []}` or 503 on failure; do not append to `_log` when `_is_server_mode()`.  
**Regression test required?** Yes — force `_conn()` to raise, assert empty/503, not foreign lines.  
**Production blocker?** Yes for tenant isolation claims.

Related (same family as F-P1-01, not a separate GO gate): `_pick_next_message` pops the bag **before** the network send (`app/campaign_queue.py` ~102–114). Process kill after claim and before `send_log` **drops** the index (lost send) unless something returns it. No idempotency key.

---

### P2

| ID | Category | Location | Evidence / impact |
|---|---|---|---|
| F-P2-01 | Auth product | `docker-compose.yml` `REGISTRATION_OPEN:-1` vs Python default closed | New prod from example is open signup + tenant SQLite/vault cost. Subscription gates start, not register. |
| F-P2-02 | Session | `JWT_EXPIRE_HOURS` 168, `remember_me=True` default | Stolen cookie lives 7 days; logout needed to revoke. |
| F-P2-03 | Isolation tests | `tests/test_cross_tenant_api.py` | Empty lists only; IDOR not exercised with data. |
| F-P2-04 | Scheduler | `scheduler_tenant_ids` except → `[None]` | PG blip mutates `ROOT/data` not a tenant, but still wrong. |
| F-P2-05 | Startup | lifespan `_try_auto_resume` with no tenant | Multi-tenant resume delayed to scheduler. |
| F-P2-06 | Celery | service token `role=admin` skips subscription | If profile enabled, unpaid start. No in-app enqueue. |
| F-P2-07 | Resources | compose: no mem/cpu limits | Noisy tenant / leak can kill VPS. |
| F-P2-08 | God module | `main.py` ~2920 lines | ADR 003 PARTIAL; change risk, hidden coupling. |
| F-P2-09 | Docs | README, AGENTS, DECISIONS, HOW-IT-WORKS | desktop/maxserverapp/per-tenant messages false. |
| F-P2-10 | Tests | deleted `test_dashboard_message_pool.py` | Flaky removed ≠ bug fixed. |
| F-P2-11 | Restore UX | `restore-volumes.sh` `read` | Cannot automate DR. |
| F-P2-12 | Leftover quarantine | `{id}.deleting`, `.outgoing-restore` | Crash mid-delete/restore. |
| F-P2-13 | Availability coupling | admin message upload resets all tenant queues | All campaigns perturbed. |
| F-P2-14 | Subscription revoke | in-flight worker does not stop immediately | Sends after paid period until scheduler. |
| F-P2-15 | SQLite | `synchronous=NORMAL` | Last transactions lost on host crash. |
| F-P2-16 | Scale | single app replica documented only in comments | Accidental `scale: 2` double-sends. |
| F-P2-17 | Runtime leak | `delete_user` never drops `REGISTRY._workers[tenant_id]` | Orphan CampaignRuntime until process restart. |
| F-P2-19 | SQLite schema | `PRAGMA foreign_keys=ON` but `group_profiles` / `send_log` have no `REFERENCES` | Orphans possible even when helper exists. |
| F-P2-20 | Impersonation | `routes_auth.exit_impersonation` vs `logout` | Exit swaps cookies; does **not** `revoke_token(jti)`. Stolen imp JWT stays valid up to 168 h (`role=admin` on victim tenant). |
| F-P2-21 | Docker | `Dockerfile` | No `USER`; `gcc`/`libffi-dev` remain in the runtime image. RCE = uid 0 on `max_server_data`. |

---

### P3

| ID | Category | Notes |
|---|---|---|
| F-P3-01 | CSP | `style-src 'unsafe-inline'` |
| F-P3-02 | Cookie | SameSite=Lax not Strict |
| F-P3-03 | Health | public `db_ok` |
| F-P3-04 | WS | accept then auth |
| F-P3-05 | Redis | password on healthcheck argv |
| F-P3-06 | CI Postgres | unpinned `postgres:16-alpine` |
| F-P3-07 | Admin webhook | SSRF by trusted admin |
| F-P3-08 | `_session_cache` | no prune of expired jti keys |
| F-P3-09 | Dual DATABASE_URL | `MAX_USE_DATABASE_URL` vs `app.config` confusing |
| F-P3-10 | Desktop PIN leftovers | dead in server mode |
| F-P3-11 | AI hooks | warn-only |
| F-P3-12 | Extra agents | unused roster files |
| F-P3-13 | Public CI dummies | `.github/workflows/ci.yml` JWT/admin/postgres/redis strings | Clearly `ci-*` / `testpass` fixtures, not GitHub Secrets. **Not** prod rotation unless those exact strings were copied to a VPS. |
| F-P3-14 | HOW-IT-WORKS env sample | `docs/HOW-IT-WORKS.md` ~529 | Russian placeholder for JWT_SECRET, not a live key. |

---

## 23. Required Fix Plan

Order for a later implementation session (do not start in this audit):

1. **F-P1-01** — cancel/stop/deploy must not requeue a message already accepted by MAX.  
2. **F-P1-02** — one shutdown path: drain workers, then encrypt, then exit.  
3. **F-P1-03** — CI install lockfiles; compile locks on 3.12.  
4. **F-P1-04** — disable auto-deploy or require manual approval + PG+lockfile verify + HTTPS.  
5. **F-P1-05** — honest DR: stop-app backup or volume snapshot; live restore test; checksums.  
6. **F-P1-06** — serialize SQLite access (or drop pool below 2 until fixed).  
7. **F-P1-07** — implement or remove `_delete_profile_if_orphan`; add a route test.  
8. **F-P1-08** — never return `main._log` to a tenant in server mode.  
9. Then P2: compose `REGISTRATION_OPEN` default aligned with policy; revoke impersonation `jti` on exit; non-root Docker USER; resource limits; cross-tenant tests with real rows; docs sweep; restore without `read` for disaster mode; prevent `app` replica scale.

---

## 24. Final Verdict

## FINAL VERDICT

STATUS: **NO-GO**

P0: **0**  
P1: **8**  
P2: **21**  
P3: **14**

Tests: **not executed in this audit** (no pass/fail counts claimed). Skipif PG modules: **6 files skipped** in any process without `DATABASE_URL`. Celery/pymax importorskip: conditional.

Production-equivalent tests: **FAIL** (no live Docker backup/restore, no cancel-after-send, no deploy-during-campaign, CI ≠ image deps)

Security: **PARTIAL** (cookie JWT, service token, tenant paths look sound; subscription bypass for service token; vault = disk key)

Tenant isolation: **FAIL** (SQLite files isolated; `/api/log` error path is a confirmed cross-tenant read)

Backup/restore: **PARTIAL** (scripts exist; hot; interactive restore; no live test)

CI/CD: **PARTIAL** (PG skipif no longer silent in smoke; auto-deploy; loose deps)

Dependency reproducibility: **FAIL**

AI harness: **PARTIAL**

Documentation consistency: **FAIL**

---

## REQUIRED BEFORE PRODUCTION

1. Fix duplicate-send on cancel (F-P1-01) with a regression test.  
2. Unify SIGTERM/lifespan so deploy/restart drains workers before encrypt/exit (F-P1-02).  
3. Make CI install and test the same lockfiles Docker ships; regenerate on Python 3.12 (F-P1-03).  
4. Remove or approval-gate `deploy.yml` auto-deploy; run PG tests on the deploy verify job; do not skip HTTPS (F-P1-04).  
5. Define and test DR: either accept “hot, inconsistent, keys-in-tarball” in an ops runbook **and** still add a maintenance-window consistent backup, or implement one. Execute restore once on a copy of prod-like volumes (F-P1-05).  
6. Serialize per-tenant SQLite (F-P1-06) before running `WORKER_POOL_SIZE>1`.  
7. Fix group delete orphan helper (F-P1-07).  
8. Stop `/api/log` from returning the process-global buffer (F-P1-08).  
9. Confirm GitHub deploy secrets are not connected until (4) is done.  
10. Confirm VPS volume + `./backups` permissions match session-token sensitivity (ADR 006).  
11. Set `REGISTRATION_OPEN` explicitly in prod `.env` (do not rely on compose default).  
12. Keep `USE_CELERY=0` until subscription is enforced on the service-token path.  
13. Do not scale the `app` service above one replica.

---

## ACCEPTED RISKS

Only if the required list above is done **or** an owner explicitly signs them:

- **Disk-key vault (ADR 006):** `.app_key` beside `session.db.enc`; backup = key + ciphertext. Protection is volume ACL, not encryption.  
- **Unofficial MAX API:** third-party messenger; ban/version breakage; CI cannot hit real MAX.  
- **SameSite=Lax + no CSRF token** for first-party cookie POSTs.  
- **Single-process asyncio workers** (no HA campaign runtime).  
- **Open registration** *if* product wants self-serve tenants and subscription remains the paid gate — but then compose default must be a conscious prod `.env`, not an accident.  
- **Admin webhook SSRF** (admin is trusted).  
- **`style-src 'unsafe-inline'`** until CSS is externalized.

---

## NOT PRODUCTION BLOCKERS

P2/P3 from section 22 (god `main.py`, CSP style, health `db_ok`, WS accept-first, Redis CLI password, extra agents, PIN leftovers, dual DATABASE_URL naming, `_session_cache` growth, docs drift, flaky-test deletion, resource limits, scheduler `[None]`, etc.). Fix after P1. Do not mix into the go/no-go gate except resource limits if the VPS is shared and untrusted tenants can already register (then F-P2-07 rises).
