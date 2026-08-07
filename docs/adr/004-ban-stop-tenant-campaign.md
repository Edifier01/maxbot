# ADR 004: Ban detection stops entire tenant campaign

**Status:** Accepted (2026-08-07)  
**Feature:** FEATURE-SAAS-UX-2026

## Context

During sending or login, MAX may return errors indicating an account is banned or blocked. Continuing the campaign with sibling accounts increases risk and wastes worker time.

## Decision

1. Classify errors with `antiban_core.is_ban_error(err)`.
2. Persist `profiles.status = 'banned'` (see `ProfileStatus.BANNED`).
3. Call `_handle_profile_banned`: set `auto_run=0`, `stop_worker(tenant_id=...)`, log reason.

## Ban vs recoverable

**Stop-all (ban-class):** ban, banned, blocked, restrict, suspend, Russian equivalents (забан, бан, блок, …).

**Do not stop tenant:** standalone flood/spam without ban words (pacing/rate-limit). Example: `"flood wait 30 seconds"`.

**Edge case:** `"blocked for spam"` matches `blocked` → stop-all.

## Consequences

- One banned account halts all sending for that tenant until admin/user restarts after remediation.
- UI badges for `banned` are frontend responsibility (Round 2).
- Substring heuristics may false-positive; tighten with word boundaries if production logs show noise.

## Implementation

- `antiban_core.is_ban_error`
- `main._mark_profile_failed` → returns `True` on ban
- `main._handle_profile_banned`
- `app/campaign_send.py`, `app/routes_profiles.py`
