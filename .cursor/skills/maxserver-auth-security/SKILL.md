---
name: maxserver-auth-security
description: MAX Sender JWT, tenant isolation, vault, and secrets checklist. Use when touching auth, impersonation, sessions, vault, or tenant data paths.
---

# MAX Sender Auth & Security

Compose (task-scoped): `security-review`, `tenant-isolation-max`, `vault-fernet-sessions`, `saas-multi-tenant`. This file wins on product rules.

**Required agent:** `security-engineer` (not “read the skill and patch JWT yourself”).

## Product facts

- Tenant id from authenticated context (`ContextVar`), never from client input for AuthZ.
- Ops data: `data/tenants/{id}/` SQLite + encrypted sessions. SaaS meta: PostgreSQL.
- Vault: Fernet/PBKDF2 per `data_dir` (`app/vault.py`, `app/vault_store.py`). ADR 006.
- Subscriptions are **admin-granted**. No payment gateway.
- Impersonation JWT must not set persistent login cookie; restore rejects `imp=true`.

## Do not

- Weaken tenant isolation or vault lock/unlock semantics.
- Log passwords, keys, or plaintext sessions.
- Replace isolation with Supabase RLS / PostgREST. Optional PG RLS is extra defense only, never the sole gate.
- Commit `.env`, keys, or vault material.

## Checklists

- [ ] AuthZ on the new/changed route (cabinet `role=user` vs admin/impersonation)
- [ ] Cross-tenant path/DB impossible
- [ ] `INTERNAL_SERVICE_TOKEN` not weakened (Celery/internal hooks)
- [ ] Vault tests still pass if crypto/session files touched

## Tests (pick relevant)

`tests/test_cross_tenant_api.py`, `test_tenant_isolation_sqlite.py`, `test_tenant_scope.py`, `test_vault.py`, `test_vault_per_tenant.py`, `test_vault_hot_path_isolation.py`
