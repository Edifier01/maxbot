# Project Status — MAX Sender

> Обновляется parent-агентом после значимых изменений.

**Last updated:** 2026-07-28 (server SaaS v1)  
**Version:** 1.13.0 (local); server SaaS scaffold added

## Overall Status

| Area | Status | Notes |
|------|--------|-------|
| Local app (run.bat / exe) | ✅ Working | Unchanged; MAX_SERVER_MODE off |
| Server SaaS auth | 🟡 MVP | Register/login, JWT, subscriptions, admin panel |
| Server Docker stack | 🟢 Updated | Postgres + MAX_SERVER_MODE in compose |
| CI/CD | 🟡 Scaffold | ci.yml + deploy.yml (needs GitHub secrets) |
| Server integration tests | 🔴 TODO | Verifier: add auth/tenant tests |
| WebSocket server auth | 🔴 TODO | WS public in server mode |

## Completed (this session)

- [x] ADR-007 multi-tenant hybrid storage
- [x] PostgreSQL schema: tenants, users, subscriptions, impersonation_log
- [x] server/app: auth, middleware, admin API, hooks bootstrap
- [x] static/auth.html, admin.html, role-based index.html
- [x] GitHub Actions CI + deploy workflow
- [x] docker-compose with Postgres + env vars

## Next Up

1. Configure GitHub secrets: DEPLOY_HOST, DEPLOY_USER, DEPLOY_SSH_KEY, DEPLOY_PATH
2. Deploy to VPS and smoke-test full auth flow
3. WebSocket JWT auth in server mode
4. Integration tests for server auth
