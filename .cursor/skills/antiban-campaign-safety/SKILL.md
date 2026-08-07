---
name: antiban-campaign-safety
description: Protects campaign pacing, warmup, and anti-ban safeguards for unofficial MAX API sending. Use before changing campaign workers or delays.
---

# Anti-Ban Campaign Safety

## Purpose

Avoid account bans and unsafe send rates when changing campaign engine behavior.

## When To Use

- Any edit to `antiban_core.py`, `app/campaign_*.py`, send/pacing logic

## When Not To Use

- Pure admin subscription UI with no send-path changes

## Workflow

1. Read ADR 002 and relevant HOW-IT-WORKS campaign sections.
2. Treat delays, warmup, role percents, and circuit breakers as safety controls — not dead weight.
3. Require explicit Feature Plan + human approval to reduce pacing aggressiveness.
4. Prefer metrics/logs to understand throughput before changing constants.
5. Run `tests/test_campaign_modules.py`, worker/tenant runtime tests as applicable.

## Validation Checklist

- [ ] No silent removal of pacing/warmup
- [ ] Per-tenant worker isolation still holds (ADR 001)
- [ ] Tests for changed behavior exist

## Related Agents

- `campaign-antiban`, `backend-architect`

## Related Rules

- `antiban-safety.mdc`
