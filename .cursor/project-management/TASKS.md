# Tasks — MAX Sender Server

## Epic: AI Harness

### Feature: Audit-project upgrade

Status: COMPLETED  
Owner: project-architect  
Depends on: none  
Scope:
- `.cursor/**`, `AGENTS.md`, `docs/MASTER-AI-WORKFLOW.md`, PM files

Tasks:
- [x] Codebase + harness audit
- [x] Gap Report + proceed
- [x] Bootstrap core + Gap ADD items
- [x] Validation checklist

Validation:
- [x] Mandatory core files present
- [x] Domain agents/skills/rules/hooks installed selectively

Notes:
- Gap Report: `Global-AI-System/knowledge-catalog/reports/max-sender-gap.md`

---

## Epic: Platform hardening (product)

### Feature: Further main.py extraction

Status: BACKLOG  
Owner: backend-architect (when started)  
Depends on: Feature Plan  
Scope:
- `main.py`, `app/` extraction slices per ADR 003

Tasks:
- [ ] Propose scoped extraction Feature Plan
- [ ] Preserve tenant worker + campaign behavior
- [ ] Tests green

Validation:
- [ ] pytest smoke + relevant module tests
- [ ] verifier PASSED

### Feature: Celery path parity hardening

Status: BACKLOG  
Owner: campaign-antiban + devops-automator  
Scope:
- `celery_worker.py`, compose profile, campaign start token path

Tasks:
- [ ] Inventory divergences vs in-process worker
- [ ] Tests for tenant header / token parity

Validation:
- [ ] `tests/test_celery_worker.py` (+ new cases)
- [ ] docs/PRODUCTION-OPS still accurate

### Feature: Hybrid backup restore drill

Status: BACKLOG  
Owner: database-reliability + devops-automator  
Scope:
- `scripts/backup-volumes.sh`, `restore-volumes.sh`, PRODUCTION-OPS

Tasks:
- [ ] Document last successful restore drill date
- [ ] Ensure PG + `max_server_data` both covered

Validation:
- [ ] Restore dry-run notes in HANDOFF/ops

---

## Epic: Out of scope (do not start)

- Payment gateway / Stripe
- SPA rewrite / mobile
- Kubernetes
