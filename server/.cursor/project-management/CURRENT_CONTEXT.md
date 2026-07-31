# Current Context

## Current Feature

Admin global settings navigation — **COMPLETED**

## Current Feature

Vault password removal (auto .app_key) — **COMPLETED**

## Key Paths

- `app/vault.py`, `main.py` — `ensure_vault_unlocked`, drop PBKDF2 vault
- `static/index.html` — removed vault modal and password UI
- `tests/test_vault.py`

## Last Updated

2026-07-31
