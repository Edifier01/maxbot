# Tasks — MAX Sender

> Parent-агент ведёт backlog. Специалисты не меняют приоритеты самостоятельно.

## Legend

- `[ ]` todo · `[~]` in progress · `[x]` done · `[—]` cancelled

---

## P0 — Infrastructure & AI System

- [x] Bootstrap AI agent system (orchestrator, verifier, skills, workflow)
- [x] Full project review (local focus) — `docs/PROJECT-REVIEW.md`
- [x] Smoke tests: health, vault, campaign pause/resume (`tests/`, `run-tests.bat`)
- [ ] Validate server deploy on VPS (Docker + Caddy + domain + PIN)

## P1 — Server Readiness

- [ ] Implement `server/app/hooks.py` (no browser, server env checks)
- [ ] Server-specific settings defaults (HOST=0.0.0.0, PIN required warning)
- [ ] Test data migration: local `data/` → Docker volume
- [ ] Harden `server/scripts/deploy.sh` (backup before deploy)

## P2 — UI / UX

- [x] Admin panel polish: loading states, error toasts (done in v1.13)
- [x] Responsive layout baseline (@media 720px)
- [x] Self-host fonts (offline exe — no Google CDN)
- [x] Onboarding wizard for first run (4 steps + skip)
- [ ] PIN-not-set / legacy-vault badges in settings
- [ ] Server mode indicator (HTTPS badge, domain display)
- [ ] Optional: public landing page (separate from admin panel)

## P3 — Backend Quality (from AUDIT.md)

- [ ] Extract repositories/services from `main.py` (incremental)
- [ ] PostgreSQL runtime adapter
- [ ] CI: lint + smoke tests
- [ ] E2E test plan for critical flows (login, campaign start/stop)

## P4 — Future

- [ ] Multi-tenancy (if needed)
- [ ] Celery production profile tuning
- [ ] Telegram notifications for campaign events

---

## Active Feature

_None — review complete; pick next from PROJECT-REVIEW §10._

## Completed (recent)

- [x] Server Docker Compose + Caddy scaffold
- [x] Curated skills for server workspace
- [x] AUDIT.md technical specification
