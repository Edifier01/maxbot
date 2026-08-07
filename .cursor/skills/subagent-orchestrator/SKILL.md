---
name: subagent-orchestrator
description: Routes scoped MAX Sender work to the smallest useful specialist agent and integrates results. Use for multi-domain changes touching desktop/server, backend/UI/database/devops/security, or when verification needs a separate pass.
disable-model-invocation: true
---

# Subagent Orchestrator

1. Load context via `context-loading` (includes zone skills).
2. Pick only necessary agents from `.cursor/agents/README.md`.
3. Attach the matching skill to each agent assignment:

| Agent | Required skill |
|-------|----------------|
| devops-engineer | `maxserver-server-deploy` |
| backend-engineer | `maxserver-fastapi-backend` |
| frontend-engineer | `maxserver-static-ui` |
| ui-designer | `maxserver-ui-workflow`, `web-design-guidelines`, `ui-ux-pro-max`, `frontend-design-max` |
| database-engineer | `maxserver-postgresql` |
| security-engineer | `maxserver-auth-security` |
| campaign-specialist | `maxserver-campaign` |
| qa-engineer | `maxserver-testing` + deploy checklist if server/infra touched |
| verifier | `maxserver-testing` + all touched domain skills |

4. Give each agent: narrow scope, target files, skill path, expected output, verification.
5. Do not let specialists update `.cursor/project-management/*`.
6. Run `verifier` after integration; security-sensitive work needs `security-engineer` evidence.
7. Parent agent integrates results, resolves conflicts, and updates project state.
