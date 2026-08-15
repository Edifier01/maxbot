# Gap Report — MAX Sender Server

**Mode:** Plan vs Reality Review (refresh of `/audit-project` phase 4)  
**Target:** `C:\Users\Maga\Documents\Projects\server`  
**Generated:** 2026-08-15  
**Previous:** 2026-08-07 (facades missing — **obsolete**)  
**Verifier:** [PASS WITH NOTES](e20e90ee-a96c-47d7-9730-bb32a334795c)

---

## Executive summary

Product plans (M1–M3, M5, FEATURE-* 2026, AGENT-FIX, SERVER-REVIEW except P3-3) match the code as scoped. The harness **is operational**: seven `maxserver-*` facades, `maxserver-harness`, `maxserver-ui-workflow`, and `.cursor/skills/README.md` are on disk.

Live pytest this pass: **165 passed, 19 skipped** (no `DATABASE_URL`). Desktop N/A (server-only workspace).

**Do not** wire extra agents, vendor `skills/`, or adopt Railway/Supabase/n8n unless a new Feature Plan says so.

---

## SOURCE COVERAGE

| Source | Status |
|--------|--------|
| Product docs, ADRs 001–007, PRODUCTION-OPS, CI, tests | ✓ |
| Orchestration skills | ✓ |
| Generic domain skills | ✓ composed via facades |
| **maxserver-* facades** | **✓ present** (was ✗ 2026-08-07) |
| `maxserver-static-ui` / `maxserver-testing` | ✓ |
| `.cursor/skills/README.md` | ✓ |
| `knowledge-catalog/sources.json` | ✓ Knowlange distillation index |
| Vendored root `skills/` | absent — do not load; not required |
| Extra Agency/AAS/ECC dump | not wired (correct) |

---

## KEEP

- Product docs + ADRs (link, do not replace)
- Core 7 specialists + orchestrator + verifier + ui-designer
- Facades composing generics (map in `.cursor/skills/README.md`)
- Proceed gate, ponytail, `/audit-harness`

---

## REPLACE (done 2026-08-15)

| Was | Now |
|-----|-----|
| 0/7 `maxserver-*` | Facades on disk |
| Missing skills README | `.cursor/skills/README.md` |
| `context-loading` forced `maxserverapp/` | Detect server-as-root |
| This report + HARNESS-AUDIT claiming broken routing | This refresh |

---

## REMOVE / do not expand

| Item | Action |
|------|--------|
| Extra personas without routing | Leave unwired or merge in a future Feature Plan — **not** this review |
| `devops-automator` / `api-tester` / `database-reliability` | Still duplicates; do not wire |
| Claim of vendored `skills/` | Keep AGENTS.md honest |

---

## ADD — remaining (not this chat)

P0 facades: **done**.

P1 extra-agent wiring: **still open** (optional). Core loop works without it.

P2: no full AAS/ECC install.

---

## Validation checklist

- [x] All seven `maxserver-*` SKILL.md exist
- [x] Specialist “Read … SKILL.md” paths exist
- [x] `.cursor/skills/README.md` present
- [x] No false vendored `skills/` claim in AGENTS.md
- [ ] Extra agents in `ai-skills-system.mdc` — **deferred** (roster bloat)
- [x] HANDOFF updated with this review

---

## Plan vs code (2026-08-15)

| Plan | Status |
|------|--------|
| PROJECT_PLAN M1–M3, M5 | ✅ (M4 billing OOS; Celery/Telegram present) |
| AGENT-FIX C/H/M/L | ✅ as scoped |
| SERVER-REVIEW P0–P3 | ✅ except **P3-3 PARTIAL** (`main.py` ~2845) |
| FEATURE-SAAS-UX, UX-OPS, VAULT-CI, REVIEW-FIX 1–2, MOBILE P0/P1 | ✅ |
| FEATURE-MOBILE P2 | **DEFERRED** |
| FEATURE-VAULT-CI D2 wording | ✅ FEATURE-RESIDUALS-2026 — 15 skipifs in separate `server-smoke` process |
| FEATURE-RESIDUALS-2026 | ✅ cookie-only JWT, CSP scripts, REGISTRATION_OPEN 0, Celery fail-closed, UI leftovers |

---

## Residuals (still open — need a Feature Plan)

1. `to_thread` beyond admin + claim
2. Further `main.py` split (ADR 003 / P3-3)
3. FEATURE-MOBILE P2 badge chrome
4. Extra-agent wiring (optional)
5. `style-src` without `'unsafe-inline'`
6. Login JSON still includes `"token"` (ADR 008 transitional); WS accepts JSON JWT only if no cookie
7. Skill/plan copy: tenant cabinet is groups/start-stop/stats (not messages/settings)

---

## Related

- Harness audit: `docs/HARNESS-AUDIT.md`
- Knowlange used/rejected: `knowledge-catalog/sources.json`
