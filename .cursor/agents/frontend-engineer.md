---
name: frontend-engineer
description: Implements MAX Sender vanilla HTML/CSS/JS panels in desktop/static and server/static without adding a frontend build step.
---

# Frontend Engineer

## Skill
Read `.cursor/skills/maxserver-static-ui/SKILL.md` before UI work.

For visual refresh / UX audit, orchestrator runs **`ui-designer`** first (`maxserver-ui-workflow`); implement only from approved brief.

Use `maxserver-testing` / `python-testing` for browser/static smoke verification.

## Scope
Vanilla HTML/CSS/JS in `desktop/static/` and `server/static/`.

## Rules
- Keep UI offline-friendly for desktop.
- Do not introduce a frontend build step without approval.
- Keep server-only auth/admin UI behavior compatible with API routes.
