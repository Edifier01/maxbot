# Universal Start Feature Workflow

## Purpose

Every generated project must have a `/start-feature` workflow.

This workflow turns a plain business request into a controlled implementation sequence:

1. load project context;
2. analyze the requirement;
3. create a Feature Plan;
4. list agents and models;
5. wait for explicit `proceed`;
6. execute scoped specialist work;
7. verify;
8. update project state.

## Command

```text
/start-feature <business goal>
```

Examples:

```text
/start-feature создать публичную страницу услуги и форму заявки
/start-feature добавить авторизацию через email и пароль
/start-feature реализовать бронирование времени у специалиста
/start-feature добавить оплату подписки
```

## Required Behavior

The command must never jump directly into code.

It must:

- load project state;
- inspect relevant decisions and tasks;
- ask at most two clarifying questions if the goal is unclear;
- classify complexity;
- invoke `project-orchestrator`;
- show a Feature Plan;
- wait for explicit user confirmation;
- only then start implementation.

Accepted confirmation examples:

```text
proceed
ok
yes
да
go ahead
начинай
```

## Complexity Classification

```text
TRIVIAL
Criteria:
- one file;
- under 10 lines;
- no logic change;
- no security or data impact.

Action:
- bypass orchestrator;
- edit directly;
- update handoff if needed.

STANDARD
Criteria:
- one to three files;
- one or two domains;
- no architecture change;
- no sensitive integration.

Action:
- Feature Plan;
- scoped implementation;
- verifier.

COMPLEX
Criteria:
- four or more files;
- three or more domains;
- architecture change;
- new external integration;
- auth, payments, PII, compliance, or security impact.

Action:
- architecture/security review if needed;
- ADR if needed;
- Feature Plan;
- specialist agents;
- verifier.
```

## Feature Plan Format

`project-orchestrator` must output:

```text
FEATURE PLAN
─────────────────────────────────────────
Feature: [name]
Complexity: LOW | MEDIUM | HIGH
ADR required: YES | NO (reason)

Domains affected:
  Frontend:  [pages/components/state/forms or "none"]
  Backend:   [services/use cases/routes/jobs or "none"]
  Database:  [models/migrations/indexes or "none"]
  API:       [contracts/endpoints/schemas or "none"]
  Mobile:    [screens/native modules/deep links or "none"]
  AI/Data:   [models/prompts/pipelines/analytics or "none"]
  Testing:   [unit/integration/E2E/manual smoke or "none"]
  Security:  [auth/PII/payments/OWASP/compliance or "none"]
  DevOps:    [CI/CD/env/deploy/infra or "none"]

Agent Assignment:
  [agent-name] -> [specific scoped task]

Model Strategy:
  GPT-5.5:      [planning/research/docs/orchestration tasks]
  Composer 2.5: [implementation/tests/migrations/routine verification]
  Opus:         [architecture/security/payments/compliance only if needed]

Execution:
  Round 1 (parallel): [agents without dependencies]
  Round 2 (sequential): [agents depending on Round 1]
  Round 3: verifier

Risks:
  - [risk and mitigation]

Validation:
  - [test/check/review]

Estimated effort: S | M | L
─────────────────────────────────────────
```

## Mission Brief Format

After the user confirms `proceed`, the parent agent or `subagent-orchestrator` creates:

```text
MISSION BRIEF
─────────────────────────────────────────
Goal: [one sentence]
Total Agents: [N]
Expected Cost: LOW | MEDIUM | HIGH

AGENTS:
[1] ID: agent-001
    Role: [Planner / Builder / Tester / Browser / Verifier]
    Agent: [.cursor/agents/name]
    Model: [composer-2.5-fast | gpt-5.5-medium | claude-opus-4-8-thinking-high]
    Scope: [exact files, folders, APIs, URLs, or domains]
    Skills: [selected skills only]
    Rules: [selected rules only]
    MCP/Tools: [only required tools]
    Depends on: [none / agent-ID]

Integration:
  Parent agent merges outputs, resolves conflicts, and updates project state.
─────────────────────────────────────────
```

## Workflow Phases

| Phase | Owner | Required |
|-------|-------|----------|
| Context loading | main agent | yes |
| Requirement analysis | `project-orchestrator` | yes |
| Feature Plan | `project-orchestrator` | yes |
| User confirmation | user | yes |
| Architecture review | architecture agent | if ADR/security/high-risk |
| Implementation | assigned specialists | yes |
| Testing | QA or relevant builder | yes |
| Security review | security agent | if auth/PII/payments/compliance |
| Verification | `verifier` | yes |
| PM update | parent agent | yes |

## Context Loading Requirement

Before planning, the workflow must read:

```text
.cursor/project-management/CURRENT_CONTEXT.md
.cursor/project-management/PROJECT_STATUS.md
.cursor/project-management/TASKS.md
.cursor/project-management/DECISIONS.md
.cursor/project-management/HANDOFF.md
```

If these files do not exist, the bootstrap agent must create them before feature work begins.

## Implementation Rules

After `proceed`:

- pass scoped context packets to specialist agents;
- run independent work in parallel where safe;
- avoid unrelated refactors;
- do not let subagents update PM-state independently unless explicitly assigned;
- parent agent integrates outputs;
- run verifier before marking done.

## Verification Result

`verifier` must report one of:

```text
PASSED
PASSED WITH NOTES
FAILED
```

If `FAILED`, the feature is not done. Fix issues and run verification again.

## Anti-Patterns

Do not:

- start coding before Feature Plan approval;
- ask unlimited clarifying questions;
- assign all agents to every feature;
- use Opus by default;
- skip tests because a change is small;
- mark completion without verifier;
- update only code and forget project state.

