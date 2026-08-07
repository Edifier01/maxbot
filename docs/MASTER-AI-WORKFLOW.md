# Master AI Workflow — MAX Sender Server

Short map of the AI harness. Details live in linked files.

## Entry

```text
/start-feature <business goal>
```

1. Load context → 2. Plan → 3. Wait for `proceed` → 4. Implement scoped → 5. Mechanical checks → 6. Verifier → 7. Update PM.

## Layers

| Layer | Path |
|-------|------|
| Map | `AGENTS.md` |
| Agents | `.cursor/agents/` |
| Skills | `.cursor/skills/` |
| Rules | `.cursor/rules/` |
| Hooks | `.cursor/hooks.json` |
| PM | `.cursor/project-management/` |
| Lifecycle | `.cursor/workflows/feature-lifecycle.md` |
| Product docs | `docs/HOW-IT-WORKS.md`, `PRODUCTION-OPS.md`, `PROJECT_PLAN.md` |
| ADRs | `docs/adr/` (index: `DECISIONS.md`) |

## Skills vs subagents

- **Skill** — procedural checklist in one context (deploy steps, vault change recipe, context load).
- **Subagent** — isolated ownership / parallel / high-risk specialty (auth, vault, campaign-antiban, devops).

## Models

- Plan: Grok (`project-orchestrator`)
- Implement: Composer (coding, tests, verifier)
- Deep: Opus-class when Feature Plan justifies (security/architecture/tenant/vault/antiban)

## Evolution

Phase 1: ADRs + Feature Plan risks (active).  
Phase 2/3: dependency graph / lessons — deferred.  
Meta reference: `Global-AI-System/ai-agent-system-bootstrap/EVOLUTION-ROADMAP.md`.
