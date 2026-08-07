# Model Routing

## Purpose

Model routing keeps the AI development system accurate, fast, and cost-conscious.

The generated project should use the least expensive model that can complete the task with the required quality.

## Default Models

| Model | Slug | Use for |
|-------|------|---------|
| Composer 2.5 | `composer-2.5-fast` | implementation, CRUD, UI, tests, migrations, routine verification |
| GPT-5.5 | `gpt-5.5-medium` | planning, orchestration, research, documentation, comparison, DevOps planning |
| Opus | `claude-opus-4-8-thinking-high` | architecture, ADRs, security, payments, compliance, high-risk domain reasoning |

## Default Agent Routing

| Agent type | Default model |
|------------|---------------|
| `project-orchestrator` | GPT-5.5 |
| `verifier` | Composer 2.5 |
| backend/frontend/database/API/QA builders | Composer 2.5 |
| DevOps planning | GPT-5.5 |
| architecture agent | Opus |
| security auditor | Opus |
| payments/billing specialist | Opus |

## Bootstrap Routing

When creating the AI system in a new project:

1. Use GPT-5.5 for product analysis, skills inventory, agent design, and workflow design.
2. Use Composer 2.5 for repetitive file creation once the structure is clear.
3. Use Opus only if the project has architecture, security, compliance, payments, or other high-risk concerns.

## Feature Routing

During `/start-feature`:

```text
Planning and Feature Plan
  -> GPT-5.5 through project-orchestrator

Implementation
  -> Composer 2.5 through scoped specialist agents

Routine verification
  -> Composer 2.5 through verifier

Architecture/security/payments/compliance
  -> Opus through the relevant specialist
```

## Escalation Rules

Escalate from Composer 2.5 to GPT-5.5 or Opus when:

- requirements are ambiguous;
- the implementation repeatedly fails;
- the work crosses many modules;
- the feature changes architecture;
- the feature touches auth, payments, PII, compliance, or safety;
- a verifier finds a serious architectural or security concern.

## Downgrade Rules

After planning or deep review is complete, move routine implementation back to Composer 2.5.

Do not keep Opus active for:

- CRUD;
- basic UI;
- form wiring;
- boilerplate;
- routine tests;
- formatting;
- documentation drafts;
- ordinary pass/fail verification.

## Feature Plan Requirement

Every Feature Plan must include a model strategy section:

```text
Model Strategy:
  GPT-5.5:      [planning/research/orchestration/docs]
  Composer 2.5: [implementation/tests/migrations/verification]
  Opus:         [architecture/security/payments/compliance only if needed]
```

If Opus is listed, the plan must explain why.

## Anti-Patterns

Do not:

- use Opus for the default orchestrator;
- use Opus for the default verifier;
- route all agents to the same model;
- use the strongest model because the task is large but repetitive;
- avoid escalation when security or payments are involved.

