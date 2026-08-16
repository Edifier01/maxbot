# Feature Lifecycle

1. Context loading (`.cursor/skills/context-loading`) + zone skills.
2. Requirement analysis.
3. Complexity classification (`desktop` | `server` | `both`).
4. Feature Plan (`.cursor/skills/start-feature`) with **Skills Assignment**.
5. User approval before implementation for medium/high-risk work.
6. Architecture/ADR note if needed.
7. Agent + skill assignment (`.cursor/rules/ai-skills-system.mdc`).
8. Implementation — specialists follow their skill checklists.
9. Testing or practical verification (`maxserver-testing`; QA uses deploy checklist for server infra).
10. Security review when auth, vault, sessions, tenant data, deployment exposure, or secrets are affected (`maxserver-auth-security`).
11. Verifier pass.
12. Documentation update.
13. Project-management update.

## Server deploy lifecycle (extra)

When DevOps domain is affected:
- Pre: checklist from `maxserver-server-deploy`
- During: `docker compose config`
- Post: health check + 15 min monitoring per `deployment-procedures` principles

## Domain gates

- UI changes: `maxserver-static-ui` + static/browser smoke when risk warrants.
- Campaign changes: `maxserver-campaign` + pause/resume/reset or sending safety scenario.
- DB migrations: `maxserver-postgresql` + backup/rollback note.
- Completion claims: `maxserver-testing` evidence first.

## Completion Rule
A task is not done until the response states what changed, what was verified, and what remains unverified.

Optional after a large diff: `/ponytail-review` (size only). Optional if agents/skills look broken: `/audit-harness`.
