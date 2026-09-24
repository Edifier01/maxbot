# Production CI and Deploy Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a manual production deploy reuse the complete CI gate, verify the real public stack, and prove restore can start PostgreSQL from a stopped state.

**Architecture:** Reuse the existing CI workflow and `scripts/deploy.sh` instead of maintaining duplicate preflight/deploy logic in YAML. Strengthen the existing verification and restore scripts in place; add no service, dependency, deployment mode, or global setting.

**Tech Stack:** GitHub Actions, Bash, Docker Compose, Python 3.12, pytest

**Spec:** `docs/superpowers/specs/2026-08-25-production-readiness-stages-1-3-design.md`

## Global Constraints

- Do not change anti-ban behavior, human behavior, roles, pacing, limits, local-day rules, global settings, or `worker_pool_size`.
- Deployment stays manual, single-app, immutable by SHA, and protected by the `production` environment.
- Do not add Celery, replicas, dependencies, or a new deployment abstraction.
- Do not push, deploy, access credentials, or contact the VPS in this plan.

---

### Task 1: Reuse the complete CI gate before deploy

**Files:**
- Modify: `.github/workflows/ci.yml:6-8`
- Modify: `.github/workflows/deploy.yml:13-36`
- Modify: `tests/test_backup_scripts.py`

**Interfaces:**
- Consumes: existing CI jobs `server-smoke`, `compose-config`, `dependency-audit`, `backup-restore-smoke`, and `server-e2e`.
- Produces: reusable workflow entry `workflow_call` and deploy job `verify` that calls `./.github/workflows/ci.yml`.

- [ ] **Step 1: Add failing workflow-policy assertions**

Extend `test_ci_actions_images_and_permissions_are_immutable` with:

```python
assert "workflow_call:" in ci
assert "uses: ./.github/workflows/ci.yml" in deploy
assert "python -m pytest tests/ -q" not in deploy
```

Run the focused test and confirm it fails because the current deploy workflow
contains its own partial pytest job.

- [ ] **Step 2: Make CI reusable and delete the duplicate verify steps**

Add `workflow_call:` under `ci.yml`'s existing `on:` block. Replace the deploy
`verify` job body with:

```yaml
  verify:
    uses: ./.github/workflows/ci.yml
```

Keep `deploy.needs: verify`, `environment: production`, and the existing
concurrency policy.

- [ ] **Step 3: Verify and commit**

Run:

```powershell
& 'C:\Users\Admin\Documents\Projects\server\.venv\Scripts\python.exe' -m pytest tests\test_backup_scripts.py -k "ci_actions or deploy_ssh" -q
```

Expected: PASS.

```powershell
git add .github/workflows/ci.yml .github/workflows/deploy.yml tests/test_backup_scripts.py
git commit -m "ci: require full release gate before deploy"
```

### Task 2: Reuse the deploy script and pin SSH identity

**Files:**
- Modify: `.github/workflows/deploy.yml:37-103`
- Modify: `scripts/deploy.sh:75-87`
- Modify: `tests/test_backup_scripts.py`

**Interfaces:**
- Consumes: `scripts/deploy.sh`, which already validates `.env`, backs up existing data, builds, starts, and verifies the stack.
- Produces: one deployment path plus required `DEPLOY_HOST_FINGERPRINT` secret input.

- [ ] **Step 1: Add failing policy assertions**

Change the deploy workflow test to assert:

```python
assert "fingerprint: ${{ secrets.DEPLOY_HOST_FINGERPRINT }}" in deploy
assert "bash scripts/deploy.sh" in deploy
assert "CHECK_HTTPS=0" not in deploy
assert "docker compose build app" not in deploy
```

Extend `test_deploy_sh_mirrors_backup_gate_and_celery_profile` with:

```python
assert "CHECK_HTTPS=0" not in deploy_sh
assert "bash scripts/verify_deploy.sh" in deploy_sh
```

Run both tests and confirm the current duplicated workflow and HTTPS override
make them fail.

- [ ] **Step 2: Delete duplicated remote deployment commands**

Keep exact SHA fetch/checkout in the SSH script. Replace everything after
`cd "$(git rev-parse --show-toplevel)"` with:

```bash
bash scripts/deploy.sh
```

Add the action input:

```yaml
fingerprint: ${{ secrets.DEPLOY_HOST_FINGERPRINT }}
```

The pinned action exposes the `fingerprint` input; the production environment
must supply the matching SHA256 host-key fingerprint before deploy can run.

- [ ] **Step 3: Require normal HTTPS verification**

In `scripts/deploy.sh`, replace the `CHECK_HTTPS=0` invocation with:

```bash
bash scripts/verify_deploy.sh || {
```

Remove the message that a later full HTTPS verification is still needed.

- [ ] **Step 4: Verify and commit**

Run the two focused tests from Task 1. Expected: PASS.

```powershell
git add .github/workflows/deploy.yml scripts/deploy.sh tests/test_backup_scripts.py
git commit -m "ops: use one fail-closed deploy path"
```

### Task 3: Verify required services and authenticated Redis health

**Files:**
- Modify: `scripts/verify_deploy.sh:16-46`
- Modify: `tests/test_backup_scripts.py`

**Interfaces:**
- Consumes: Compose services `app`, `postgres`, `redis`, `caddy`; `INTERNAL_SERVICE_TOKEN`; authenticated `/api/health` fields `db_ok`, `redis_configured`, and `redis_ok`.
- Produces: non-zero verification when a required service, PostgreSQL, Redis, or public HTTPS is unhealthy.

- [ ] **Step 1: Add failing script-contract assertions**

Add a test that reads `verify_deploy.sh` and asserts it contains each required
service name, passes `Authorization: Bearer` to internal health, and rejects
`redis_ok` unless it is true when Redis is configured. Also assert the script
still performs the HTTPS curl.

- [ ] **Step 2: Add the smallest service gate**

After `docker compose ps`, loop over `app postgres redis caddy`. For each,
require `docker compose ps "$service" --status running -q` to return an ID;
otherwise print the service logs and exit 1.

- [ ] **Step 3: Authenticate the internal health request**

Pass `INTERNAL_SERVICE_TOKEN` into the existing Python health probe and set an
`Authorization: Bearer <token>` header. Make the probe succeed only when
`db_ok is True` and, if `redis_configured` is true, `redis_ok is True`.

- [ ] **Step 4: Verify and commit**

Run `tests/test_backup_scripts.py`. Expected: PASS.

```powershell
git add scripts/verify_deploy.sh tests/test_backup_scripts.py
git commit -m "ops: verify the complete public stack"
```

### Task 4: Prove restore starts PostgreSQL

**Files:**
- Modify: `scripts/restore-volumes.sh:18-62`
- Modify: `scripts/dr-smoke.sh:20-24`
- Modify: `tests/test_backup_scripts.py`

**Interfaces:**
- Consumes: Compose `postgres` healthcheck and `pg_isready`.
- Produces: restore that starts/waits for PostgreSQL before `pg_restore`, plus CI smoke that stops PostgreSQL before invoking restore.

- [ ] **Step 1: Add failing DR assertions**

Extend the restore test to assert `docker compose up -d postgres` and a
`pg_isready` readiness loop both occur before `pg_restore`. Extend the DR-smoke
test to assert `docker compose stop postgres` occurs after backup and before
`restore-volumes.sh --yes`.

- [ ] **Step 2: Start and wait for PostgreSQL in restore**

Immediately before PostgreSQL restore, run `docker compose up -d postgres` and
reuse the existing ten-attempt, two-second `pg_isready` pattern from
`scripts/deploy.sh`. On timeout, show PostgreSQL logs and exit before changing
PostgreSQL.

- [ ] **Step 3: Make CI exercise the stopped-PostgreSQL path**

After mutating the smoke data and before restore, add:

```bash
docker compose stop postgres
```

- [ ] **Step 4: Verify and commit**

Run `tests/test_backup_scripts.py`. Expected: PASS. Bash syntax and the real
Docker DR run remain GitHub/Linux gates.

```powershell
git add scripts/restore-volumes.sh scripts/dr-smoke.sh tests/test_backup_scripts.py
git commit -m "ops: make restore start postgres fail closed"
```

### Task 5: Align the production runbook with enforced gates

**Files:**
- Modify: `docs/PRODUCTION-OPS.md`
- Modify: `migrations/README.md`

**Interfaces:**
- Consumes: the completed CI, deploy, verify, and restore behavior from Tasks 1–4.
- Produces: one accurate operator checklist; no runtime interface.

- [ ] **Step 1: Update the runbook**

Document all five CI jobs, the fingerprint secret, full HTTPS/service/Redis
verification, the stopped-PostgreSQL restore smoke, and rollback safety:
forward-only migrations require the matching pre-deploy backup unless the
previous SHA is explicitly schema-compatible.

Correct the metrics example to include:

```bash
-H "Authorization: Bearer $INTERNAL_SERVICE_TOKEN"
```

Clarify that Redis is reconstructed runtime state and is not part of the
authoritative PG+SQLite backup pair.

- [ ] **Step 2: Correct migration documentation**

State that Compose mounts only `schema_pg.sql` into `initdb.d`; Python applies
`migrations/*.sql` at application startup.

- [ ] **Step 3: Verify and commit**

Run `git diff --check` and review the two documentation diffs against the
implemented Tasks 1–4. Human-facing prose intentionally has no source-string
pytest assertions.

```powershell
git add docs/PRODUCTION-OPS.md migrations/README.md
git commit -m "docs: align production gates and rollback policy"
```
