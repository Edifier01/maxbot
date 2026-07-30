# Agent System Specification

## Purpose

This specification defines the AI development system that the bootstrap agent should create in a new project.

The generated system must preserve the operating model from this repository:

- project state is loaded before work;
- features start through `/start-feature`;
- `project-orchestrator` creates the Feature Plan;
- implementation waits for explicit `proceed`;
- specialist agents work in scoped domains;
- `verifier` validates work before completion;
- project-management state is updated after each session.

## Target Folder Structure

```text
.cursor/
├── agents/
│   ├── README.md
│   ├── project-orchestrator.md
│   ├── verifier.md
│   └── [domain-agent].md
├── project-management/
│   ├── CURRENT_CONTEXT.md
│   ├── PROJECT_STATUS.md
│   ├── TASKS.md
│   ├── DECISIONS.md
│   └── HANDOFF.md
├── skills/
│   ├── context-loading/
│   │   └── SKILL.md
│   ├── start-feature/
│   │   └── SKILL.md
│   ├── subagent-orchestrator/
│   │   └── SKILL.md
│   └── [project-skill]/
│       └── SKILL.md
└── workflows/
    └── feature-lifecycle.md

docs/
└── MASTER-AI-WORKFLOW.md
```

The bootstrap agent may also create `docs/adr/` if the project needs Architecture Decision Records.

## Mandatory Components

Every project must have these components.

### `project-orchestrator`

Role:

- receives business goals;
- analyzes requirements;
- reads project-management state;
- selects relevant agents and skills;
- creates the Feature Plan;
- never writes application code.

Required settings:

```yaml
---
name: project-orchestrator
description: Main feature coordinator. Produces Feature Plans and routes work to project-specific agents. Never writes application code.
model: gpt-5.5-medium
readonly: true
---
```

### `verifier`

Role:

- checks claimed work against the Feature Plan;
- verifies implementation, tests, security, docs, and project-management state;
- rejects incomplete work;
- escalates to architecture/security agents only when needed.

Required settings:

```yaml
---
name: verifier
description: Validates completed work before it can be marked done.
model: composer-2.5-fast
readonly: true
---
```

### `context-loading` skill

Role:

- reads project state before any work;
- ensures agents know current context, tasks, decisions, and handoff notes.

### `start-feature` skill

Role:

- accepts `/start-feature <business goal>`;
- loads context;
- invokes `project-orchestrator`;
- shows Feature Plan;
- waits for `proceed`.

### `subagent-orchestrator` skill

Role:

- executes approved Feature Plans;
- decomposes work into scoped subagent packets;
- runs independent agents in parallel;
- routes dependent work sequentially;
- returns outputs to parent agent for integration.

## Optional Domain Agents

Create optional agents only when the project's logic requires them.

| Domain need | Agent example |
|-------------|---------------|
| Web UI, components, forms, state | `frontend-engineer` |
| Backend services, use cases, APIs | `backend-engineer` |
| Schema, migrations, indexes | `database-engineer` |
| REST, OpenAPI, API versioning | `api-engineer` |
| Browser and regression tests | `qa-engineer` |
| Docker, CI/CD, deployment | `devops-engineer` |
| Auth, PII, OWASP, compliance | `security-auditor` |
| Payments, billing, webhooks | `payments-specialist` |
| Mobile apps | `mobile-engineer` |
| Data pipelines, analytics, ML | `data-engineer` |
| LLM features and AI workflows | `ai-engineer` |
| Booking, reservations, calendars | `booking-specialist` |
| CRM leads, accounts, pipelines | `crm-specialist` |
| Courses, lessons, progress | `learning-specialist` |
| Products, inventory, pricing | `catalog-specialist` |
| Logistics, shipments, returns | `logistics-specialist` |

The bootstrap agent should name domain agents using the product's language, not the source project's language.

## Agent Creation Rules

Each generated agent must include:

- frontmatter with `name`, `description`, `model`, and `readonly`;
- role;
- responsibilities;
- decision boundaries;
- escalation triggers;
- allowed skills;
- allowed rules;
- allowed MCP/tools;
- allowed file or domain scope;
- required workflow;
- output format;
- related agents.

## Skills Inventory Requirement

Before creating agents, the bootstrap agent must inspect the full `skills` folder.

For each skill, record:

```text
Skill:
Purpose:
When to use:
Relevant project domains:
Allowed agents:
Notes:
```

Then map selected skills to agents:

```text
Agent:
Allowed skills:
Reason:
```

Skills must be assigned intentionally. A generic "all agents can use all skills" rule is not allowed.

## Project Management State

The generated `.cursor/project-management/` files should follow this responsibility split:

| File | Purpose |
|------|---------|
| `CURRENT_CONTEXT.md` | 30-second orientation for the next agent |
| `PROJECT_STATUS.md` | current phase, objective, blockers, next actions |
| `TASKS.md` | master task registry |
| `DECISIONS.md` | decision index and ADR links |
| `HANDOFF.md` | what happened in the last session and what to do next |

Agents must read state before work. The parent agent updates state after work.

## Agent Selection Policy

Use the smallest effective team.

Examples:

```text
Marketing website:
- project-orchestrator
- frontend-engineer
- seo-specialist
- qa-engineer
- verifier

Mobile fitness app:
- project-orchestrator
- mobile-engineer
- backend-engineer
- database-engineer
- qa-engineer
- verifier

SaaS CRM:
- project-orchestrator
- frontend-engineer
- backend-engineer
- database-engineer
- crm-specialist
- security-auditor
- qa-engineer
- verifier

Payments product:
- project-orchestrator
- payments-specialist
- backend-engineer
- api-engineer
- security-auditor
- qa-engineer
- verifier
```

## Anti-Patterns

Do not:

- create all possible agents;
- create agents for tiny UI parts;
- create domain agents before domain analysis;
- assign all skills to all agents;
- make `project-orchestrator` write code;
- make `verifier` modify code;
- skip project-management state;
- skip `/start-feature`;
- skip the `proceed` gate;
- use expensive models for routine work.

