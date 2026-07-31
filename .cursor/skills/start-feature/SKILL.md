---
name: start-feature
description: Creates a Feature Plan for MAX Sender before non-trivial work. Use when the user says /start-feature or asks for a feature, refactor, deployment change, or risky behavior change.
disable-model-invocation: true
---

# Start Feature

Produce a Feature Plan and wait for approval before implementation unless the user explicitly asked to proceed immediately.

## Template
FEATURE PLAN
Feature: [name]
Complexity: LOW | MEDIUM | HIGH
ADR required: YES | NO, with reason

Domains affected:
- Desktop:
- Server:
- Backend:
- Frontend:
- Database:
- Security:
- DevOps:
- Testing:

Agent Assignment:
- [agent] -> [scoped task]

Skills Assignment:
- [skill] -> [why required for this feature]

Execution:
- Round 1:
- Round 2:
- Round 3:

Risks:
- [risk and mitigation]

Verification:
- [commands/checks/manual steps]
