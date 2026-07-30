# ADR 002: Campaign scale pacing — 1 worker, short delay, percent roles

## Status

Accepted (2026-07-30)

## Context

Target layout: ~1000 accounts in ~34 groups (~30 accounts/group), **1 proxy per group**, **1 worker** (`worker_pool_size=1`).

Global round-robin with 60–180 s post-send delay cannot complete ~2550 daily sends within send windows. Consecutive sends already rotate **group → group** (different proxy); long universal delay is redundant for IP isolation.

## Decision

1. **Keep 1 worker** — no per-group worker processes in this phase.
2. **Short inter-send delay**: `delay_min_sec=5`, `delay_max_sec=15` (not zero).
3. **Daily limits**: `daily_limit_min=5`, `daily_limit_max=10`.
4. **Percent role plan**: `day_skip_percent=40`, `role_active_percent=30`, `role_quiet_percent=30` (quiet uses `role_quiet_limit=1`).
5. **Weaken human_pauses** so long breaks do not negate short delays (`long_pause_chance=3`, `break_after_n=8`, shorter break/long-pause seconds).
6. **Keep** send windows and `human_rhythm_enabled`.
7. **Soft migration** `campaign_scale_v18` for existing SQLite tenants — update only if settings still match previous factory values.

## Consequences

- Higher throughput (~2550 sends/day feasible with presence overhead).
- Increased ban-risk vs legacy 60–180 s — mitigated by windows, roles, proxy-per-group, presence.
- Legacy role mode remains when `role_active_percent=0` (`role_active_min/max`).
- Custom tenant overrides preserved unless they match old factory values targeted by v18 migration.

## Alternatives considered

- Per-group worker + separate queue state — deferred (larger refactor).
- `delay=0` — rejected (too aggressive).
- Per-group worker without delay — rejected in favor of minimal 5–15 s buffer.
