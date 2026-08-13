# ADR 006: Per-tenant vault hot path

**Status:** Accepted  
**Date:** 2026-08-09  
**Feature:** FEATURE-VAULT-CI-2026  
**Related:** ADR 001 (tenant worker isolation)

## Context

MAX Sender encrypts MAX session files (`session.db.enc`) with Fernet. Two vault implementations coexist:

1. **`main.py` process-global** — module-level `_fernet`, `_vault_unlocked`, and paths `SESSIONS` / `_APP_KEY_PATH` under a single `DATA`. Encrypt/decrypt/session_dir/unlock on the hot path historically used this global state.
2. **`app.vault` + `app.vault_store`** — Fernet cache keyed by `data_dir` (`store_key(data_dir)` → in-memory `(Fernet | None, unlocked)`). Paths resolve via `app.paths` (`app_key_path`, `sessions_root`, etc.).

In server mode each tenant has `data/tenants/{id}/` (ADR 001). A process-global Fernet/SESSIONS can decrypt or write under the wrong tenant after ContextVar changes, or stick the first unlocked key across tenants. Workers outlive requests; sticky globals are unsafe.

**At-rest model (current product):** each data dir holds `.app_key` beside `sessions/`. `ensure_vault_unlocked` auto-loads (or creates) that key — no user PIN/password unlock in the panel. Password/PBKDF2 files (`.app_salt` / `.app_vault`) are dropped when encountered. Backups of `max_server_data` therefore contain both ciphertext and the key material needed to decrypt it.

## Decision

1. **Hot path resolves per `data_dir`** — in server mode, all encrypt/decrypt/session_dir/unlock (and status used by send readiness) must resolve the effective directory via `_resolve_data_dir()` / `get_effective_data_dir(ROOT)` and call **`app.vault`** (backed by **`vault_store`**), not process-global `_fernet` / `SESSIONS`.
2. **Keep per-tenant `.app_key` auto-unlock** — intentional disk-key encryption for operational simplicity; no PIN/Scrypt vault unlock restore in this feature (locked 2026-08-09).
3. **Threat model is volume theft** — encryption protects casual file copies and plaintext session dumps on disk; it does **not** protect against an attacker who obtains the data volume or a backup that includes `.app_key` + `session.db.enc`. Ops must treat `max_server_data` (and backups) as secret material equivalent to session tokens.
4. **Desktop/local** may retain a single data dir; the same `app.vault(data_dir=…)` API is preferred so one code path serves both modes.

## Consequences

- Positive: tenant A session crypto cannot use tenant B’s Fernet or write under tenant B’s `sessions/`.
- Positive: docs/ops align with real behavior (auto-unlock, backup = key + ciphertext).
- Negative: volume/backup compromise decrypts sessions without a separate unlock secret.
- Residual: module path globals (`SESSIONS` / `_APP_*`) may still exist for pytest `_refresh_data_paths`; crypto hot path must not use them (implemented 2026-08-09).

## Out of scope

- Restoring user PIN / Scrypt / PBKDF2 unlock UX for the vault
- External KMS / Hashicorp Vault
- Changing backup scripts beyond documenting sensitivity (see `backup-hybrid-storage`, PRODUCTION-OPS)

## Alternatives Considered

- **PIN/Scrypt unlock restore** — stronger against volume theft; rejected for this feature (ops friction; D1 locked).
- **Keep global `_fernet` with path refresh only** — insufficient; Fernet instance itself must be per `data_dir`.
