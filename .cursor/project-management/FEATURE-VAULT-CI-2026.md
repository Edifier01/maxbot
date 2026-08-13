# Feature Plan — Vault hot-path isolation + CI PG gate

**Status:** COMPLETE (2026-08-09)  
**Zone:** `server`  
**Complexity:** HIGH  
**ADR:** ADR-006 (accepted)

## Locked decisions (Ed, 2026-08-09)

| # | Decision |
|---|----------|
| D1 | `.app_key` at-rest: **document threat model only** — no PIN/Scrypt unlock restore in this feature |
| D2 | CI: **Postgres on `server-smoke`** so `DATABASE_URL` skipif modules cannot silently skip |
| D3 | Lockfiles in CI: **out of scope** (G-4 stands) |

## Delivered

1. Vault/session hot path → `app.vault` / `vault_store` via `_resolve_data_dir()`; multi-tenant shutdown encrypt
2. ADR-006 + HOW-IT-WORKS `.app_key` threat model
3. CI: Postgres + `DATABASE_URL` on `server-smoke`
4. `tests/test_vault_hot_path_isolation.py` (+ per-tenant hot-path smoke)

## Verification evidence

- Verifier: PASS WITH NOTES (56c95f7b…) — static OK; pytest blocked in Ask sandbox
- Security spot-check: PASS WITH NOTES (4da280c8…)
- Parent pytest: **110 passed, 13 skipped** (local without DATABASE_URL); vault subset green
- Agents: security ADR e3cb7f15…, devops 15b477e9…, backend ce6c2f60…, qa design 4b9a2ee9… (file landed by parent)

## Optional follow-ups (out of this feature)

- Deprecate/gate unused `/api/vault/setup|unlock` footgun
- Impersonation `/api/admin` when `imp`; cookie-only/CSP; deploy auto-backup; CI lockfiles
