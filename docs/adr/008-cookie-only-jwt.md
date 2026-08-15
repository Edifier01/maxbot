# ADR 008: Cookie-only user JWT

**Status:** Accepted  
**Date:** 2026-08-15  
**Feature:** FEATURE-RESIDUALS-2026  
**Related:** ADR 006 (vault), remember-me persistent login

## Context

User JWTs were accepted from either `Authorization: Bearer` or the HttpOnly `max_token` cookie. The frontend stored the JWT in JavaScript (`localStorage` / memory) and sent it as Bearer. That keeps a long-lived credential reachable to XSS. Impersonation returned a JSON token and did not set a cookie, so the admin UI also had to hold JWTs in JS to enter and exit impersonation.

`INTERNAL_SERVICE_TOKEN` (Celery → `POST /api/campaign/start|schedule`, Prometheus `/metrics`) already uses Bearer and must stay that way.

## Decision

1. **User JWT is only the HttpOnly cookie `max_token`.** Middleware authenticates users from `request.cookies.get("max_token")`. A user JWT in `Authorization: Bearer` is ignored (not decoded, not used as fallback).
2. **`Authorization: Bearer` is only for `INTERNAL_SERVICE_TOKEN`.** Metrics requires the service token. Internal campaign start/schedule require the service token plus `X-Tenant-Id`. An empty service token does not authenticate.
3. **Login/register always set `max_token`.** `remember_me=True` → `Max-Age = JWT_EXPIRE_HOURS * 3600`. `remember_me=False` → session cookie (no Max-Age).
4. **Impersonation sets a session `max_token`** (imp JWT, no Max-Age) and a session HttpOnly backup `max_admin_token` with the admin’s current JWT. `POST /api/auth/exit-impersonation` restores the backup as `max_token` and clears `max_admin_token`. `POST /api/auth/restore-session` still rejects `imp=true` cookies.
5. **Logout** reads the user token from the cookie (not Bearer), revokes `jti`, and clears both cookies.
6. **WebSocket `/ws/status` (server mode)** authenticates from the handshake cookie `max_token`. First message must still be `{type: auth}` (desktop PIN path unchanged). JSON `token` is used only if no cookie is present; a cookie wins over JSON.

## Consequences

- Positive: XSS cannot exfiltrate a Bearer user JWT from JS once the client stops storing it (Round 2 frontend extract).
- Positive: Admin can exit impersonation without keeping a JWT in JS.
- Negative: Non-browser clients (curl, scripts) must send `-b max_token=...` for user/admin APIs. Service token Bearer is unchanged for metrics/Celery.
- Residual: JSON responses still include `"token"` for tests and transitional clients. Round 2 removes JS Bearer usage. CSP `script-src 'self'` is a separate residual.

## Out of scope

- Extracting inline frontend JS / cookie-only client (Round 2)
- Caddy CSP `script-src 'self'` (Round 2)
- Changing `INTERNAL_SERVICE_TOKEN` checks or Celery enqueue headers

## Alternatives Considered

- **Keep Bearer as fallback for user JWT** — rejected; XSS and stolen tokens stay useful.
- **Separate persistent vs session cookie names** — unnecessary; Max-Age vs session on the same `max_token` is enough.
