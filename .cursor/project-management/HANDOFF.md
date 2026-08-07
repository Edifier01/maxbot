# Handoff

## Last session

2026-08-07 — `/audit-project` phases 6–8: AI harness upgrade applied to MAX Sender Server after Gap Report `proceed`.

## Done

- Bootstrap core: AGENTS.md, orchestrator, verifier, context-loading, start-feature, subagent-orchestrator, PM, feature-lifecycle, MASTER-AI-WORKFLOW
- Domain agents (7 Agency-adapted + campaign-antiban)
- Skills (ECC adapted + AAS saas-multi-tenant adapted + project-local)
- Rules (7) + hooks (3 Cursor-adapted)
- KEEP product docs untouched

## Next action

Run first product Feature Plan:

```text
/start-feature Harden Celery vs in-process campaign start parity (tenant headers + INTERNAL_SERVICE_TOKEN) with tests
```

Alternate:

```text
/start-feature Extract next safe slice from main.py into app/ per ADR 003 without changing campaign behavior
```

## Blockers

None for harness. Product risks remain: unofficial MAX API, hybrid backup discipline, monolith residue.

## Notes for next agent

- Read `AGENTS.md` + this file + `CURRENT_CONTEXT.md` first.
- Do not install full Agency/AAS/ECC catalogs.
- Payments are out of scope.
