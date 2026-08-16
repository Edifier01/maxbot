# FEATURE PLAN — P3 review residuals 2026-08-16

**Status:** COMPLETE (2026-08-16) — verifier [PASS WITH NOTES](ceb43ba6-7e23-4fc7-b5d1-4270fb71cb39); QA pytest **197 passed, 26 skipped**; `docker compose config -q` OK  
**Zone:** `server`  
**Complexity:** MEDIUM  
**ADR required:** NO — enforces ADR 001 (per-tenant claim) and ADR 004 (flood ≠ ban)

Source: project review 2026-08-16 canvas P3. User: «приступай к P3» after P2 complete.

## In scope

1. Delete unused `app/campaign_store.py` (zero imports; duplicated in `campaign_worker`).
2. Flood-wait: parse `wait N seconds` from send errors; sleep `max(RETRY_DELAYS[attempt], N)`. Flood stays non-ban (ADR 004).
3. Per-tenant `claim_lock` on `CampaignRuntime`; drop process-global `main._claim_lock`.
4. Backup verify after write: non-empty `pg.dump` + `gzip -t` / tar listing of `data.tar.gz`. Do **not** stop the live app (hot backup stays hot).
5. Pin compose sidecar images (`postgres`, `redis`, `caddy`) by digest, same pattern as `Dockerfile` Python base.
6. Tests: mocked MAX profile login happy path; `send_with_retry` one success; flood-wait sleep; per-tenant claim locks differ.

## Out of scope

- `style-src 'unsafe-inline'` (FEATURE-RESIDUALS / P2 deferred)
- PIN vault / volume-theft crypto (ADR 006)
- `main.py` split (ADR 003)
- `asyncio.to_thread` remaining SQLite/PG
- Docker non-root USER (P2 leftover)
- Global TXT live-queue reset; `worker_pool_size` delay scale (P2 leftover)
- Quiesce/sqlite `.backup` API for live SQLite (hot tar + archive verify only)

## Agent Assignment

| Agent | Task |
|-------|------|
| campaign-specialist | 2–3, 6 (flood-wait, claim_lock, send_with_retry success + flood/lock tests) |
| backend-engineer | 1, 6 (delete `campaign_store.py`; mocked `POST /api/profiles/{id}/login` happy path) |
| devops-engineer | 4–5: backup-volumes.sh verify + compose digest pins + `test_backup_scripts.py` + PRODUCTION-OPS note |
| qa-engineer | After merge: pytest + `docker compose config -q` |
| verifier | Evidence gate |

## Skills Assignment

| Skill | Why |
|-------|-----|
| maxserver-campaign | flood wait, claim lock, send retry |
| antiban-campaign-safety | do not treat flood as ban; do not shorten delays |
| maxserver-fastapi-backend | dead module, login route test |
| maxserver-server-deploy | compose pins, backup script |
| backup-hybrid-storage | archive verify without wiping live data |
| maxserver-testing | pytest + compose-config evidence |

## Execution

- Round 1 (parallel): campaign, backend, devops
- Round 2: parent integrate
- Round 3: qa + verifier

## Risks

| Risk | Mitigation |
|------|------------|
| Huge flood wait hangs worker | Sleep the parsed N (correct); tests mock `asyncio.sleep` |
| Digest pin stale | `ponytail:` quarterly refresh like Dockerfile Python pin |
| Per-tenant lock races pool workers | Same tenant still serializes claims; only cross-tenant parallelism changes |
| Backup verify false-fail on empty volume | Require archive readable + at least one tar member **or** documented empty-volume exception |

## Verification

```
MAX_TEST=1 MAX_SERVER_MODE=1 python -m pytest tests/ -q
docker compose config -q
```
Expect: P3 tests pass; compose still valid with digest-pinned sidecars.
