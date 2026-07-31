# Decisions

## Decision Log

| ID | Date | Status | Summary | Link |
|----|------|--------|---------|------|
| D-001 | 2026-07-28 | accepted | Two independent distributions: desktop + server | — |
| D-002 | 2026-07-28 | accepted | Minimal agent set for MAX Sender domains | `.cursor/agents/README.md` |
| D-003 | 2026-07-28 | accepted | Active skills in `.cursor/skills/`, not vendored `skills/` wholesale | `.cursor/skills/README.md` |
| D-004 | 2026-07-30 | accepted | AI system bootstrap from `ai-agent-system-bootstrap/` — model routing, proceed gate, PROJECT_PLAN | `docs/MASTER-AI-WORKFLOW.md` |
| D-005 | 2026-07-30 | accepted | security-engineer defaults to Opus; orchestrator GPT-5.5; verifier Composer 2.5 | `.cursor/agents/` |
| D-006 | 2026-07-30 | accepted | Manual subscriptions only — no payment gateway in scope | `docs/PROJECT_PLAN.md` |
| D-007 | 2026-07-30 | accepted | Scale pacing v18: 1 worker, delay 5–15, roles 40/30/30, soft migration | `docs/adr/002-campaign-scale-pacing.md` |
| D-008 | 2026-07-31 | accepted | Role plan: ordered 3-day rotation 33/33/33; anchor on first campaign start, no reset on restart; remainder to first parts | — |

## 2026-07-31: Role Rotation (D-008)

When `role_plan_enabled`:

1. Profiles split into 3 ordered thirds (`order_index`); remainder `n%3` goes to earlier parts.
2. 3-day cycle from `role_cycle_anchor` (set once on first campaign start).
3. Part roles offset by part index so each day has exactly one third active, quiet, skip.
4. Legacy percent settings (`day_skip_percent`, `role_active_percent`, `role_quiet_percent`) not used in role-plan mode.

## 2026-07-28: Server Standalone

This folder is a self-contained server project. Open as workspace root; desktop not required.

## 2026-07-30: Bootstrap Applied

Non-negotiable behaviors from bootstrap spec:

- `/start-feature` → Feature Plan → wait for `proceed`
- project-orchestrator readonly, no app code
- verifier readonly, PASSED/FAILED gate
- File ownership before parallel agent work
- TASKS.md operational registry with statuses
