---
name: frontend-design-max
description: Distinctive but feasible visual direction for MAX Sender vanilla static UI. Use after audit, before frontend-engineer implements. Adapted from Knowlange frontend-design.
source: Knowlange/agentic-awesome-skills (community)
---

# Frontend Design — MAX Sender

Designer-engineer stance for **production HTML/CSS/JS**, not mockups.

## Hard constraints

- Implement via `maxserver-static-ui` — **no build step**, no Tailwind unless explicitly approved.
- Extend existing `:root` tokens; avoid wholesale palette rewrites in one PR.
- Must remain usable for long sessions (campaign operators, admins).

## Mandatory thinking (before code)

1. **Purpose** — what action must get easier? (scan status, start/stop, manage accounts)
2. **Tone** — pick one: *industrial utilitarian*, *refined dark SaaS*, *dense cockpit*, *calm minimal*
3. **Memorable element** — one deliberate choice (typography scale, header density, stat cards)
4. **Restraint** — every change serves the tone; no decoration for its own sake

## DFII (quick)

Score 1–5 each: Aesthetic Impact, Context Fit, Feasibility, Performance; subtract Consistency Risk.

| DFII | Action |
|------|--------|
| 12–15 | Proceed |
| 8–11 | Proceed, small scope |
| ≤7 | Narrow scope or safer polish only |

## Deliverable: Design Brief (markdown)

```markdown
## Direction
## Token changes (--accent, --bg-elev, …)
## Components touched
## Do NOT change (business logic, tab structure, API calls)
## Acceptance (visual + a11y)
```

Hand off brief to **frontend-engineer**.

## Anti-patterns (banned)

- Purple/neon “AI app” gradients
- Emoji as icons
- Hover scale that shifts layout
- Replacing Manrope with Inter/system default without reason
- Breaking subscription/campaign UX from FEATURE-SAAS-UX-2026

## Pair with

- `ui-ux-pro-max` — palettes, UX rules, `--design-system` CLI
- `web-design-guidelines` — compliance audit
