---
name: vault-fernet-sessions
description: Guides safe changes to MAX Sender Fernet/PBKDF2 vault and encrypted MAX session files. Use for vault unlock/setup, crypto, or session storage work.
---

# Vault Fernet Sessions

## Purpose

Protect MAX session material at rest using the existing vault design.

## When To Use

- Editing `app/vault.py`, `vault_store.py`, `routes_vault.py`
- Backup/restore involving encrypted sessions

## When Not To Use

- Cloud KMS / Hashicorp Vault migrations without ADR
- Generic `.env` deploy wiring (use devops + secrets agent)

## Workflow

1. Read existing vault module and `tests/test_vault.py`, `test_vault_per_tenant.py`.
2. Preserve PBKDF2/Fernet parameters unless ADR + security review.
3. Keep per-tenant vault state isolation.
4. Never log passwords, keys, or plaintext sessions.
5. Coordinate backups: encrypted blobs remain encrypted; key material is critical.
6. Run vault-related pytest targets.

## Validation Checklist

- [ ] No secret leakage in logs/responses
- [ ] Per-tenant vault tests pass
- [ ] Unlock/lock lifecycle intact

## Related Agents

- `secrets-credential`, `appsec-engineer`

## Related Rules

- `vault-secrets.mdc`
