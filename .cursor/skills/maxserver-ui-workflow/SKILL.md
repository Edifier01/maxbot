---
name: maxserver-ui-workflow
description: End-to-end UI improvement workflow for MAX Sender static panels — audit, design direction, implement, verify. Use for /improve-ui or visual refresh requests.
---

# MAX Sender UI Improvement Workflow

Source skills adapted from Knowlange `agentic-awesome-skills` (`ui-ux-pro-max`, `web-design-guidelines`, `frontend-design`).

## When to use

- Visual polish, dashboard/admin UX, accessibility fixes, design consistency
- **Not** for API/backend/campaign logic (use domain skills)

## Pipeline

```
1. ui-designer     → audit + design brief (tokens, priorities)
2. ui-designer     → optional design-system CLI (ui-ux-pro-max)
3. frontend-engineer → implement in static/*.html
4. qa-engineer     → smoke + static tests
5. verifier        → gate before done
```

## Step 1 — Audit

**Agent:** `ui-designer`  
**Skills:** `web-design-guidelines`, `ui-ux-pro-max`, `maxserver-static-ui`

1. Read target files (`static/index.html`, `static/admin.html`, `static/auth.html`).
2. Fetch Vercel Web Interface Guidelines (see `web-design-guidelines` skill).
3. Output findings as `file:line` + severity (CRITICAL/HIGH/MEDIUM).
4. Run design-system search for product context:

```powershell
$env:PYTHONIOENCODING='utf-8'
python .cursor/skills/ui-ux-pro-max/scripts/search.py "SaaS dashboard B2B messaging admin dark" --design-system -p "MAX Sender" -f markdown
```

Map recommendations to existing CSS variables — **do not** introduce Tailwind/build step.

## Step 2 — Design brief

**Agent:** `ui-designer`  
**Skill:** `frontend-design-max`

Produce a short brief:

- **Aesthetic direction** (one named stance, e.g. *industrial utilitarian dark*)
- **Token deltas** (which `--*` vars change, contrast targets)
- **Component list** (header, nav, tables, badges, forms)
- **Anti-patterns to avoid** (AI purple gradients, emoji icons, layout-shift hovers)
- **DFII score** if direction is risky (see `frontend-design-max`)

Wait for user OK on brief before large visual changes.

## Step 3 — Implement

**Agent:** `frontend-engineer`  
**Skill:** `maxserver-static-ui`

- Minimal diff; reuse existing classes before inventing new ones.
- Keep both panels consistent.
- No new dependencies.

## Step 4 — Verify

**Agent:** `qa-engineer`  
**Skills:** `maxserver-testing`, `web-design-guidelines` (re-audit)

```powershell
$env:MAX_TEST=1; $env:MAX_SERVER_MODE=1; python -m pytest tests/test_saas_ux_static.py tests/ -q
```

Manual: 375px / 768px / 1024px, keyboard focus, subscription UX.

## Step 5 — Verifier gate

**Agent:** `verifier` — evidence of tests + audit checklist closed or deferred with reason.

## Delegation

| Step | Agent |
|------|-------|
| Audit + brief | `ui-designer` |
| HTML/CSS/JS | `frontend-engineer` |
| Tests | `qa-engineer` |
| Final | `verifier` |

Orchestrator owns `.cursor/project-management/*` updates.

## Entry command

User: `/improve-ui [scope]` — see `.cursor/commands/improve-ui.md`
