# Handoff

## How Future Agents Should Start
1. Determine workspace root. Canonical project root is `maxserverapp/`; prefix paths if opened from the parent folder.
2. Read `README.md` and `AGENTS.md`.
3. Read `.cursor/project-management/CURRENT_CONTEXT.md`, `PROJECT_STATUS.md`, `TASKS.md`, `DECISIONS.md` and `HANDOFF.md`.
4. Identify whether the work targets `desktop/`, `server/`, or both.
5. Load matching project skills from `.cursor/skills/`.
6. Use `/start-feature ...` for non-trivial changes.
7. Update these project-management files after meaningful work.

## Important Rule
Specialist agents must not edit project-management state independently. The parent agent owns integration and handoff updates.

## Skills Library

Do not load `skills/` wholesale. It is a vendored reference library; active distilled skills are in `.cursor/skills/`.
