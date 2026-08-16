---
name: maxserver-server-deploy
description: MAX Sender Docker Compose, Caddy, VPS deploy, CI, and backup/restore. Use for Dockerfile, compose, Caddyfile, deploy scripts, or production ops.
---

# MAX Sender Server Deploy

Compose (task-scoped): `deployment-patterns`, `docker-patterns`, `redis-patterns` (health/rate-limit), `backup-hybrid-storage`. This file wins on this stack.

Stay on **existing VPS + Compose + Caddy**. Do not migrate to Railway/serverless.

## Paths

When this folder is the Cursor root: compose/Dockerfile live here (not `server/server/`). In the parent monorepo, working directory is `server/`.

| Artifact | Role |
|----------|------|
| `docker-compose.yml` / `Dockerfile` | App + Postgres + Redis + Caddy |
| `Caddyfile` | TLS, CSP, X-Frame-Options |
| `scripts/deploy.sh`, `verify_deploy.sh` | Prod deploy + health |
| `scripts/backup-volumes.sh`, `restore-volumes.sh` | PG + `max_server_data` |
| `docs/PRODUCTION-OPS.md` | Runbook |
| `.github/workflows/` | `server-smoke`, `compose-config`, `server-e2e` |

Lockfiles pin Docker installs; CI still uses `requirements*.txt` (G-4). Do not commit `.env`.

## Pre-deploy

- [ ] CI green for the jobs you touched
- [ ] `.env` has no `change-me*`
- [ ] Backup before prod upgrade
- [ ] `docker compose config -q` with required env vars

## After compose/Caddy/env edits

```powershell
docker compose config -q
```

Health: `bash scripts/verify_deploy.sh` (or `/api/health` with `db_ok: true`). Auth/secrets in the same change → `maxserver-auth-security`. Schema → `maxserver-postgresql`.
