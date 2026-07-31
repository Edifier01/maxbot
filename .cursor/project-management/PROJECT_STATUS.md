# Project Status

## Stable Areas
- Desktop local UI and smoke flow are preserved in `desktop/`.
- Server Docker stack is self-contained in `server/`.

## Active Risks
- Core logic exists as separate copies in `desktop/main.py` and `server/main.py`; shared fixes may need mirrored edits.
- MAX integration uses an unofficial API and can cause account, session, and security risks.
- Server mode includes auth, tenant data isolation, JWT, admin, and deployment concerns.

## Verification Baseline
- Python syntax check for main entrypoints passed after the split.
- `docker compose config --quiet` passes in `server/` when required env vars are supplied.
- `python scripts/check_core_sync.py --strict` — antiban + core symbol parity (CI job `core-sync`).
- Full tests: `desktop/tests/` + `server/tests/` (CI jobs `desktop-smoke`, `server-smoke`).
